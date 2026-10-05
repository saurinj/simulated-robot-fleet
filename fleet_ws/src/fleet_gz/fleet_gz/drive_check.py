#!/usr/bin/env python3
"""Project 2 motion assertion: the robot actually moved.

Records /odom x, runs drive_test (0.3 m/s for 3 s) as a subprocess,
records /odom x again, and asserts displacement ~= 0.9m.

Prints PASS/FAIL, exits 0/1.
"""
import subprocess
import sys
import time

import rclpy
from rclpy.duration import Duration
from rclpy.node import Node
from nav_msgs.msg import Odometry


EXPECTED_M = 0.9
TOLERANCE_M = 0.2
TIMEOUT_S = 15.0


class OdomReader(Node):
    def __init__(self):
        super().__init__('drive_check')
        self.x = None
        self.create_subscription(Odometry, '/odom', self._on_odom, 10)

    def _on_odom(self, msg):
        self.x = msg.pose.pose.position.x


def read_x(node, timeout):
    node.x = None
    deadline = node.get_clock().now() + Duration(seconds=timeout)
    while node.x is None and rclpy.ok():
        rclpy.spin_once(node, timeout_sec=0.5)
        if node.get_clock().now() >= deadline:
            break
    return node.x


def main():
    rclpy.init()
    node = OdomReader()
    x0 = read_x(node, TIMEOUT_S)
    if x0 is None:
        print('FAIL: no /odom before drive')
        code = 1
    else:
        t0_wall = time.monotonic()
        try:
            with open('/tmp/drive_test.log', 'w') as log:
                proc = subprocess.run(['ros2', 'run', 'fleet_gz', 'drive_test',
                            '--ros-args', '-p', 'use_sim_time:=True'],
                        check=False, stdout=log, stderr=subprocess.STDOUT,
                        timeout=60)
        except subprocess.TimeoutExpired:
            print('FAIL: drive_test hung >60s (is /clock flowing?)')
            code = 1
        else:
            wall_s = time.monotonic() - t0_wall
            print(f'drive_test subprocess: exit={proc.returncode} '
              f'wall={wall_s:.1f}s (log: /tmp/drive_test.log)')
            x1 = read_x(node, TIMEOUT_S)
            if x1 is None:
                print('FAIL: no /odom after drive')
                code = 1
            else:
                dx = x1 - x0
                if abs(dx - EXPECTED_M) <= TOLERANCE_M:
                    print(f'PASS: robot moved {dx:.2f}m '
                        f'(expected ~{EXPECTED_M:.1f}m)')
                    code = 0
                else:
                    print(f'FAIL: robot moved {dx:.2f}m, '
                        f'expected ~{EXPECTED_M:.1f}m')
                    code = 1
    node.destroy_node()
    rclpy.shutdown()
    sys.exit(code)


if __name__ == '__main__':
    main()
