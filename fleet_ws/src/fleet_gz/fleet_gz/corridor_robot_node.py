#!/usr/bin/env python3
"""RobotNode: obstacle-aware driver (the 'brain' under test).

Subscribes to /scan, publishes /cmd_vel at 10 Hz. Drives forward at
0.25 m/s until the forward lidar sector reads < 0.8 m, then stops by
publishing zero velocity continuously.

This node contains the AUTONOMY BEHAVIOR. It is the code under test.
The test harness (stop_check) observes from the outside and asserts.
RobotNode knows nothing about tests, pass bands, or timeouts.
"""
import math

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import LaserScan
from geometry_msgs.msg import Twist, Vector3

FORWARD_SPEED = 0.25      # m/s
STOP_DIST_M = 0.8         # stop when forward sector < this
SECTOR_HALF_DEG = 30.0    # forward wedge half-angle
RANGE_MIN = 0.05          # ignore closer than this (sensor noise)
RANGE_MAX = 12.0          # ignore farther than this
PUBLISH_HZ = 10.0


class RobotNode(Node):
    def __init__(self):
        super().__init__('robot_node')
        self.latest_scan = None
        self.stopped = False
        self.create_subscription(LaserScan, '/scan', self.on_scan, 10)
        self.cmd_pub = self.create_publisher(Twist, '/cmd_vel', 10)
        self.create_timer(1.0 / PUBLISH_HZ, self.tick)
        self.get_logger().info(
            f'RobotNode: driving at {FORWARD_SPEED} m/s until '
            f'forward sector < {STOP_DIST_M} m')

    def on_scan(self, msg: LaserScan):
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
        if self.latest_scan is None:
            return  # no perception yet; stay silent
        if not self.stopped and self.sector_min() < STOP_DIST_M:
            self.stopped = True
            self.get_logger().info(
                f'Obstacle at {self.sector_min():.2f} m — stopping.')
        speed = 0.0 if self.stopped else FORWARD_SPEED
        self.cmd_pub.publish(Twist(linear=Vector3(x=speed)))


def main():
    rclpy.init()
    node = RobotNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
