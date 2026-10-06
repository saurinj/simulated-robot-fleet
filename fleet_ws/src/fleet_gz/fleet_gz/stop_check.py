#!/usr/bin/env python3
"""Lidar-gated stop assertion for corridor_world.sdf (DRAFT, prepared 2026-10-05).

Drives forward at 0.25 m/s down the corridor and STOPS when the forward
±30° lidar sector reads below STOP_RANGE_M. PASS if the final /odom x lands
in [2.4, 3.4] — i.e. the robot halted 0.35–1.35 m before the obstacle face
at x = 3.75 — FAIL otherwise (drove into it, or never saw it).

Expected numbers: at 0.25 m/s with a 0.8 m stop threshold, the expected
stop x ≈ 3.75 − 0.8 = 2.95 m (minus any forward offset of the lidar mount).

Conventions inherited from the Oct 5 drive_test/scan_check fixes:
- use_sim_time: all timing in sim seconds (deterministic under the
  ~55–70% realtime software rendering).
- wait for the first /clock before latching t0 — every clock read before
  the first /clock is the epoch-0 landmine.
- exit 0/1 so run_harness.sh can consume it like scan_check/drive_check.

Assumes: corridor_world.sdf running, /scan + /odom + /clock bridged
(/clock bridging was added Oct 5; the /lidar → /scan mapping in
config/bridge.yaml applies unchanged).
"""

import math
import sys

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from sensor_msgs.msg import LaserScan

FORWARD_SPEED = 0.25
STOP_RANGE_M = 0.8          # stop when forward sector min drops below this
SECTOR_HALF_DEG = 30        # forward ±30°, same sector as scan_check
PASS_X_MIN, PASS_X_MAX = 2.4, 3.4
TIMEOUT_SIM_S = 40.0
RANGE_MIN, RANGE_MAX = 0.05, 12.0   # validity band for a scan sample


class StopCheck(Node):
    def __init__(self):
        super().__init__('stop_check')
        self.pub = self.create_publisher(Twist, '/cmd_vel', 10)
        self.latest_scan = None
        self.latest_x = None
        self.create_subscription(LaserScan, '/scan', self.on_scan, 10)
        self.create_subscription(Odometry, '/odom', self.on_odom, 10)

        # wait for the first /clock tick before latching t0 (epoch-0 fix)
        self.get_logger().info('waiting for first /clock tick...')
        while rclpy.ok() and self.get_clock().now().nanoseconds == 0:
            rclpy.spin_once(self, timeout_sec=0.1)
        self.t0 = self.get_clock().now()
        self.get_logger().info(
            f'driving at {FORWARD_SPEED} m/s until forward sector < {STOP_RANGE_M} m')
        self.timer = self.create_timer(0.1, self.tick)

    def on_scan(self, msg):
        self.latest_scan = msg

    def on_odom(self, msg):
        self.latest_x = msg.pose.pose.position.x
    
    def sector_min(self):
        """Min valid range in the forward ±SECTOR_HALF_DEG sector.

        Forward is derived from the scan's own angle_min/angle_increment,
        so this is correct regardless of which way index 0 points.
        """
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

    def stop(self):
        msg = Twist()  # all zeros
        self.pub.publish(msg)

    def finish(self, passed, reason):
        self.stop()
        x = self.latest_x
        xs = f'{x:.2f} m' if x is not None else 'unknown'
        self.get_logger().info(
            f'{"PASS" if passed else "FAIL"}: {reason} (final odom x = {xs})')
        raise SystemExit(0 if passed else 1)

    def tick(self):
        t = (self.get_clock().now() - self.t0).nanoseconds / 1e9

        if self.latest_scan is None or self.latest_x is None:
            # data-based readiness: don't drive blind
            if t > TIMEOUT_SIM_S:
                self.finish(False, 'timed out waiting for /scan or /odom')
            return

        d = self.sector_min()
        if d < STOP_RANGE_M:
            x = self.latest_x
            if PASS_X_MIN <= x <= PASS_X_MAX:
                self.finish(True,
                            f'stopped {3.75 - x:.2f} m before the obstacle face')
            else:
                self.finish(False,
                            f'stopped outside the expected band '
                            f'[{PASS_X_MIN}, {PASS_X_MAX}]')
            return

        if t > TIMEOUT_SIM_S:
            self.finish(False, 'timed out: never saw the obstacle')
            return

        msg = Twist()
        msg.linear.x = FORWARD_SPEED
        self.pub.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = StopCheck()
    code = 0
    try:
        rclpy.spin(node)
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 0
    finally:
        node.destroy_node()
        rclpy.shutdown()
    sys.exit(code)


if __name__ == '__main__':
    main()
