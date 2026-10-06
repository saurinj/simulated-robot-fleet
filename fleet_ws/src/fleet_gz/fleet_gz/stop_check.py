#!/usr/bin/env python3
"""StopCheck: pure observer/examiner for the corridor scenario.

Subscribes to /scan, /odom, /cmd_vel. Publishes NOTHING.
Watches the brain (corridor_robot_node) drive, waits for /cmd_vel to
go to zero, then asserts:
  - Final odom x in [2.4, 3.4] (stopped in the right place).
  - Final forward lidar distance < 0.8 m (stopped because of the obstacle).
Exits 0 on PASS, 1 on FAIL. For CI consumption.

Run after the bringup and corridor_robot_node are up:
  ros2 run fleet_gz stop_check --ros-args -p use_sim_time:=True
"""
import math

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import LaserScan
from nav_msgs.msg import Odometry
from geometry_msgs.msg import Twist

PASS_X_MIN = 2.4
PASS_X_MAX = 3.4
STOP_DIST_M = 0.8
SECTOR_HALF_DEG = 30.0
RANGE_MIN = 0.05
RANGE_MAX = 12.0
TIMEOUT_SIM_S = 40.0
STOPPED_CMD_THRESH = 0.01   # |cmd_vel| below this counts as stopped
STOPPED_CONFIRM_S = 2.0     # must hold for this long (sim seconds)


class StopCheck(Node):
    def __init__(self):
        super().__init__('stop_check')
        self.latest_scan = None
        self.latest_x = None
        self.latest_cmd = None
        self.t0 = None
        self.done = False
        self.saw_driving = False
        self.stopped_since = None
        self.create_subscription(LaserScan, '/scan', self.on_scan, 10)
        self.create_subscription(Odometry, '/odom', self.on_odom, 10)
        self.create_subscription(Twist, '/cmd_vel', self.on_cmd, 10)
        self.create_timer(0.1, self.tick)
        self.get_logger().info('StopCheck: observing (publishes nothing). '
                               'Waiting for first /clock tick...')

    def on_scan(self, msg: LaserScan):
        self.latest_scan = msg

    def on_odom(self, msg: Odometry):
        self.latest_x = msg.pose.pose.position.x

    def on_cmd(self, msg: Twist):
        self.latest_cmd = msg.linear.x

    def sector_min(self) -> float:
        msg = self.latest_scan
        half_rad = math.radians(SECTOR_HALF_DEG)
        valid = []
        for i, r in enumerate(msg.ranges):
            a = msg.angle_min + i * msg.angle_increment
            a = (a + math.pi) % (2 * math.pi) - math.pi
            if abs(a) <= half_rad and math.isfinite(r) \
                    and RANGE_MIN < r < RANGE_MAX:
                valid.append(r)
        return min(valid) if valid else float('inf')

    def tick(self):
        if self.done:
            return
        now = self.get_clock().now()
        if self.t0 is None:
            if now.nanoseconds == 0:
                return  # no /clock yet
            self.t0 = now
            self.get_logger().info(
                'StopCheck: clock live. Waiting for the brain to drive...')
            return
        t = (now - self.t0).nanoseconds / 1e9

        if self.latest_cmd is None or self.latest_x is None \
                or self.latest_scan is None:
            if t > TIMEOUT_SIM_S:
                self.finish(False, 'timed out waiting for /scan, /odom, or /cmd_vel')
            return

        # Phase 1: wait until the brain is actually driving.
        if not self.saw_driving:
            if abs(self.latest_cmd) > 0.1:
                self.saw_driving = True
                self.get_logger().info('StopCheck: brain is driving. Watching for stop...')
            elif t > TIMEOUT_SIM_S:
                self.finish(False, 'timed out: brain never started driving')
            return

        # Phase 2: wait for a sustained stop command.
        if abs(self.latest_cmd) < STOPPED_CMD_THRESH:
            if self.stopped_since is None:
                self.stopped_since = t
            elif t - self.stopped_since >= STOPPED_CONFIRM_S:
                self.evaluate()
                return
        else:
            self.stopped_since = None  # still moving; reset

        if t > TIMEOUT_SIM_S:
            self.finish(False, 'timed out: brain never stopped')

    def evaluate(self):
        """The brain stopped. Assert it stopped in the right place for the
        right reason."""
        d_final = self.sector_min()
        x = self.latest_x
        in_band = PASS_X_MIN <= x <= PASS_X_MAX
        saw_obstacle = d_final < STOP_DIST_M
        ok = in_band and saw_obstacle
        detail = (f'final odom x = {x:.2f} m (band [{PASS_X_MIN}, {PASS_X_MAX}]), '
                  f'final lidar = {d_final:.2f} m')
        if ok:
            self.finish(True, f'stopped correctly. {detail}')
        else:
            reasons = []
            if not in_band:
                reasons.append('outside position band')
            if not saw_obstacle:
                reasons.append('no obstacle in range (wrong reason to stop?)')
            self.finish(False, f'{", ".join(reasons)}. {detail}')

    def finish(self, ok: bool, detail: str):
        if self.done:
            return
        self.done = True
        # NOTE: publishes nothing — pure observer.
        msg = f'{"PASS" if ok else "FAIL"}: {detail}'
        self.get_logger().info(msg)
        raise SystemExit(0 if ok else 1)


def main():
    rclpy.init()
    node = StopCheck()
    try:
        rclpy.spin(node)
    except SystemExit as e:
        raise
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
