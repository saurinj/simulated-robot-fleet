#!/usr/bin/env python3
"""Project 2 perception assertion: the robot sees the obstacle.

Subscribes to /scan, takes the minimum valid range in the forward
+/-30-degree sector, and asserts an obstacle is within EXPECTED_MAX_M.

This is the harness's first *perception* check: not "did we send a
command" but "do the robot's senses match physical reality."
box_1 sits at (2.0, 1.0) in test_world.sdf, ~1.9m from the lidar at its
nearest corner, so the forward sector must read < 3.0m.

Prints PASS/FAIL and exits 0/1 so a CI runner can consume it directly.
"""
import math
import sys

import rclpy
from rclpy.duration import Duration
from rclpy.node import Node
from sensor_msgs.msg import LaserScan


FORWARD_HALF_ANGLE = math.radians(30)  # sector: -30..+30 deg around heading
EXPECTED_MAX_M = 3.0                   # box_1 nearest corner is ~1.9m out
TIMEOUT_S = 10.0


class ScanCheck(Node):
    def __init__(self):
        super().__init__('scan_check')
        self.min_forward = None
        self.create_subscription(LaserScan, '/scan', self._on_scan, 10)

    def _on_scan(self, msg):
        if self.min_forward is not None:
            return  # first valid scan is enough
        n = len(msg.ranges)
        center = n // 2  # angle 0 (forward) for a symmetric -pi..pi scan
        half = int(FORWARD_HALF_ANGLE / msg.angle_increment)
        sector = msg.ranges[max(0, center - half):center + half + 1]
        valid = [r for r in sector
                 if math.isfinite(r) and msg.range_min <= r <= msg.range_max]
        if valid:
            self.min_forward = min(valid)


def main():
    rclpy.init()
    node = ScanCheck()
    deadline = node.get_clock().now() + Duration(seconds=TIMEOUT_S)
    while node.min_forward is None and rclpy.ok():
        rclpy.spin_once(node, timeout_sec=0.5)
        if node.get_clock().now() >= deadline:
            break
    if node.min_forward is None:
        print(f'FAIL: no valid /scan received within {TIMEOUT_S:.0f}s')
        code = 1
    elif node.min_forward < EXPECTED_MAX_M:
        print(f'PASS: obstacle seen at {node.min_forward:.2f}m '
              f'(forward sector, expected < {EXPECTED_MAX_M:.1f}m)')
        code = 0
    else:
        print(f'FAIL: nearest forward obstacle at {node.min_forward:.2f}m, '
              f'expected < {EXPECTED_MAX_M:.1f}m')
        code = 1
    node.destroy_node()
    rclpy.shutdown()
    sys.exit(code)


if __name__ == '__main__':
    main()
