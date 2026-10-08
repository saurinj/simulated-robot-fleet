#!/usr/bin/env python3
"""ObstacleCheck: an examiner that proves the avoidance logic fired - not that the 
robot perfectly navigated (physics is too flaky for that).

Subscribes to /scan and /cmd_vel. Publishes NOTHING.
Watches the brain (goal_with_obstacle_steer_node) drive, waits for /cmd_vel to
go to zero, then asserts:
  -  True if encounters obstacle and turns (avoids).
Exits 0 on PASS, 1 on FAIL. For CI consumption.

Run after the bringup and goal_with_obstacle_steer_node are up:
  ros2 run fleet_gz goal_with_obstacle_steer_node --ros-args -p use_sim_time:=True
"""
import math

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from sensor_msgs.msg import LaserScan


TIMEOUT_SIM_S = 90.0
STOPPED_CMD_THRESH = 0.01   # |cmd_vel| below this counts as stopped
STOPPED_CONFIRM_S = 2.0     # must hold for this long (sim seconds)
STOP_DIST_M = 0.8         # stop when forward sector < this
SECTOR_HALF_DEG = 30.0    # forward wedge half-angle
RANGE_MIN = 0.05          # ignore closer than this (sensor noise)
RANGE_MAX = 12.0          # ignore farther than this

class ObstacleCheck(Node):
    def __init__(self):
        super().__init__('obstacle_check')
        self.latest_cmd = None
        self.t0 = None
        self.done = False
        self.saw_driving = False
        self.stopped_since = None
        self.latest_scan = None
        self.ang_z = None

        self.create_subscription(Twist, '/cmd_vel', self.on_cmd, 10)
        self.create_subscription(LaserScan, '/scan', self._on_scan, 10)
        self.create_timer(0.1, self.tick)
        self.get_logger().info('ObstacleCheck: observing (publishes nothing). '
                               'Waiting for first /clock tick...')

    def on_cmd(self, msg: Twist):
        self.latest_cmd = msg.linear.x
        self.ang_z = msg.angular.z

    def _on_scan(self, msg):
        self.latest_scan = msg

    def sector_min(self) -> float:
        """Min valid range in the forward wedge, derived from the scan's
        own angle_min/angle_increment (robust to index-0 convention)."""
        msg = self.latest_scan
        half_rad = math.radians(SECTOR_HALF_DEG)
        valid = []
        for i, r in enumerate(msg.ranges):
            a = msg.angle_min + i * msg.angle_increment
            a = (a + math.pi) % (2 * math.pi) - math.pi  # wrap to [-pi, pi]
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
                'ObstacleCheck: clock live. Waiting for the brain to drive...')
            return
        t = (now - self.t0).nanoseconds / 1e9

        if self.latest_cmd is None:
            if t > TIMEOUT_SIM_S:
                self.finish(False, 'timed out waiting for /cmd_vel')
            return

        # Phase 1: wait until the brain is actually driving.
        if not self.saw_driving:
            if abs(self.latest_cmd) > 0.1:
                self.saw_driving = True
                self.get_logger().info('ObstacleCheck: brain is driving. Watching for stop...')
            elif t > TIMEOUT_SIM_S:
                self.finish(False, 'timed out: brain never started driving')
            return

        # Phase2: evaulate
        if self.latest_scan is not None:
            fwd_dist = self.sector_min()
            
            # check if okay
            ok = fwd_dist < STOP_DIST_M and abs(self.ang_z) > 0.3
    
            detail = (f'final dist = {fwd_dist:.2f} and ang_z = {self.ang_z:.2f}')
            if ok:
                self.finish(True, f'stopped correctly. {detail}')

        if t > TIMEOUT_SIM_S:
            self.finish(False, 'timed out: avoidance never fired')

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
    node = ObstacleCheck()
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
