#!/usr/bin/env python3
"""Simulated fleet robot.

Publishes fleet_msgs/RobotTelemetry at a configurable rate with
realistically drifting values:
  - battery drains over time (faster while in FAULT)
  - temperature does a mean-reverting random walk (hotter while in FAULT)
  - position wanders inside a 20x20 m box
  - random faults occur and clear on their own (tunable probabilities)

Configuration is via ROS parameters so it can be tuned per-robot at launch
and pushed over the air at runtime (CMD_SET_PARAM, see OTA_PARAMS):
  - robot_id            (string, default "robot_1")
  - publish_rate_hz     (double, default 10.0, clamped to [0.5, 50.0])
  - fault_probability   (double, default 0.001, per-publish-tick)
  - recover_probability (double, default 0.05,  per-publish-tick)

Subscribes to ~/command (fleet_msgs/RobotCommand) for fleet-issued commands.
"""

import math
import random

import rclpy
from rclpy.node import Node
from rclpy.parameter import Parameter

from fleet_msgs.msg import RobotCommand, RobotTelemetry

# Simulation tuning
BATTERY_DRAIN_PCT_PER_S = 0.05   # ~33 min from full to empty
FAULT_DRAIN_MULTIPLIER = 4.0     # faults are expensive
ROBOT_SPEED_M_S = 0.4
ARENA_HALF_SIZE_M = 10.0
TEMP_NOMINAL_C = 41.0
TEMP_FAULT_C = 58.0

# OTA-tunable parameters: name -> (min, max) clamp range.
# robot_id is deliberately absent: a robot's identity never changes over
# the air. The robot is the authority on this allowlist -- the bridge only
# checks the command code, because a compromised publisher could bypass the
# bridge and talk DDS directly.
OTA_PARAMS = {
    'publish_rate_hz': (0.5, 50.0),
    'fault_probability': (0.0, 1.0),
    'recover_probability': (0.0, 1.0),
}


class RobotNode(Node):

    def __init__(self):
        super().__init__('robot_node')

        self.declare_parameter('robot_id', 'robot_1')
        self.declare_parameter('publish_rate_hz', 10.0)
        self.declare_parameter('fault_probability', 0.001)
        self.declare_parameter('recover_probability', 0.05)

        self.robot_id = str(self.get_parameter('robot_id').value)

        # ---- simulated physical state ----
        self.battery_pct = 100.0
        self.temperature_c = 38.0
        self.x = random.uniform(-5.0, 5.0)
        self.y = random.uniform(-5.0, 5.0)
        self.heading = random.uniform(0.0, 2 * math.pi)
        self.status = RobotTelemetry.STATUS_OK
        # A fault injected by operator command latches: it stays until an
        # explicit clear command arrives. Random (simulated) faults keep
        # auto-recovering on their own.
        self._commanded_fault = False

        self.pub = self.create_publisher(RobotTelemetry, 'telemetry', 10)
        self.cmd_sub = self.create_subscription(
            RobotCommand, 'command', self.on_command, 10)

        # Fixed 20 Hz base timer; publishing is gated on the configured rate
        # so publish_rate_hz can change at runtime without rebuilding timers.
        self._accum = 0.0
        self._last = self.get_clock().now()
        self.timer = self.create_timer(0.05, self.on_tick)

        self.get_logger().info(f'[{self.robot_id}] online, publishing telemetry')

    # ------------------------------------------------------------------ tick

    def on_tick(self):
        now = self.get_clock().now()
        dt = (now - self._last).nanoseconds / 1e9
        self._last = now

        rate = float(self.get_parameter('publish_rate_hz').value)
        rate = max(0.5, min(rate, 50.0))

        self._accum += dt
        if self._accum >= 1.0 / rate:
            self._accum = 0.0
            self.step_simulation(self._accum or dt)
            self.publish_telemetry()

    def step_simulation(self, dt):
        # --- random fault injection / recovery ---
        fault_p = float(self.get_parameter('fault_probability').value)
        recover_p = float(self.get_parameter('recover_probability').value)
        if self.status != RobotTelemetry.STATUS_FAULT:
            if random.random() < fault_p:
                self.status = RobotTelemetry.STATUS_FAULT
                self.get_logger().warn(f'[{self.robot_id}] FAULT injected')
        elif not self._commanded_fault:
            # Random faults self-heal. A commanded fault latches: it skips
            # the recovery roll and stays until the operator clears it.
            if random.random() < recover_p:
                self.status = RobotTelemetry.STATUS_OK
                self.get_logger().info(f'[{self.robot_id}] recovered from FAULT')

        # --- battery ---
        drain = BATTERY_DRAIN_PCT_PER_S * dt
        if self.status == RobotTelemetry.STATUS_FAULT:
            drain *= FAULT_DRAIN_MULTIPLIER
        self.battery_pct = max(0.0, self.battery_pct - drain)

        # Low battery degrades the robot (unless it is already faulted).
        if self.status == RobotTelemetry.STATUS_OK and self.battery_pct < 20.0:
            self.status = RobotTelemetry.STATUS_DEGRADED
        elif self.status == RobotTelemetry.STATUS_DEGRADED and self.battery_pct >= 20.0:
            self.status = RobotTelemetry.STATUS_OK

        # --- temperature: mean-reverting random walk ---
        target = TEMP_FAULT_C if self.status == RobotTelemetry.STATUS_FAULT else TEMP_NOMINAL_C
        self.temperature_c += (target - self.temperature_c) * 0.01
        self.temperature_c += random.uniform(-0.15, 0.15)

        # --- position: wander with wall bounce ---
        self.heading += random.uniform(-0.6, 0.6) * dt
        self.x += math.cos(self.heading) * ROBOT_SPEED_M_S * dt
        self.y += math.sin(self.heading) * ROBOT_SPEED_M_S * dt
        if abs(self.x) > ARENA_HALF_SIZE_M:
            self.heading = math.pi - self.heading
            self.x = max(-ARENA_HALF_SIZE_M, min(ARENA_HALF_SIZE_M, self.x))
        if abs(self.y) > ARENA_HALF_SIZE_M:
            self.heading = -self.heading
            self.y = max(-ARENA_HALF_SIZE_M, min(ARENA_HALF_SIZE_M, self.y))

    def publish_telemetry(self):
        msg = RobotTelemetry()
        msg.robot_id = self.robot_id
        msg.battery_pct = float(self.battery_pct)
        msg.temperature_c = float(self.temperature_c)
        msg.x = float(self.x)
        msg.y = float(self.y)
        msg.status = self.status
        msg.stamp = self.get_clock().now().to_msg()
        self.pub.publish(msg)

    # --------------------------------------------------------------- command

    def on_command(self, msg: RobotCommand):
        if msg.command == RobotCommand.CMD_SET_PUBLISH_RATE:
            rate = max(0.5, min(float(msg.value), 50.0))
            self.set_parameters([Parameter('publish_rate_hz', Parameter.Type.DOUBLE, rate)])
            self.get_logger().info(f'[{self.robot_id}] publish rate -> {rate} Hz')
        elif msg.command == RobotCommand.CMD_INJECT_FAULT:
            self.status = RobotTelemetry.STATUS_FAULT
            self._commanded_fault = True
            self.get_logger().warn(
                f'[{self.robot_id}] FAULT injected by command (latched)')
        elif msg.command == RobotCommand.CMD_CLEAR_FAULT:
            self._commanded_fault = False
            if self.status == RobotTelemetry.STATUS_FAULT:
                self.status = RobotTelemetry.STATUS_OK
                self.get_logger().info(f'[{self.robot_id}] FAULT cleared by command')
        elif msg.command == RobotCommand.CMD_SHUTDOWN:
            self.get_logger().warn(f'[{self.robot_id}] shutdown commanded')
            raise SystemExit
        elif msg.command == RobotCommand.CMD_SET_PARAM:
            self._apply_ota_param(msg.param_name, float(msg.value))

    def _apply_ota_param(self, name: str, value: float):
        """Apply an over-the-air config push for one tunable parameter."""
        bounds = OTA_PARAMS.get(name)
        if bounds is None:
            self.get_logger().warn(
                f'[{self.robot_id}] rejected OTA param {name!r}: not tunable')
            return
        lo, hi = bounds
        clamped = max(lo, min(value, hi))
        self.set_parameters(
            [Parameter(name, Parameter.Type.DOUBLE, clamped)])
        self.get_logger().info(
            f'[{self.robot_id}] OTA config: {name} -> {clamped}')


def main(args=None):
    rclpy.init(args=args)
    node = RobotNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
