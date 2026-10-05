#!/usr/bin/env python3
"""Scripted smoke test for the Project 2 starter.

Drives the Gazebo diff-bot forward at 0.3 m/s for 3 seconds, then stops.
No keyboard needed -- this is the repeatable check that teleop can't give
you, and the shape of things to come for the regression harness.

Verify with:  ros2 topic echo /odom
(pose.pose.position.x should grow to ~0.9 m while it drives.)
"""

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist

DRIVE_SECONDS = 3.0
FORWARD_SPEED = 0.3


class DriveTest(Node):
    def __init__(self):
        super().__init__('drive_test')
        self.pub = self.create_publisher(Twist, '/cmd_vel', 10)
        self.wait_for_clock()
        self.t0 = self.get_clock().now()
        self.timer = self.create_timer(0.1, self.tick)
        self.get_logger().info(
            f'driving forward {FORWARD_SPEED} m/s for {DRIVE_SECONDS} s')

    def wait_for_clock(self):
        # With use_sim_time, now() is epoch 0 until the first /clock
        # arrives. Capturing t0 before that makes the first /clock
        # look like hours elapsed, ending the drive instantly.
        # (Wall-clock mode: now() is immediately non-zero, no wait.)
        while rclpy.ok():
            if self.get_clock().now().nanoseconds > 0:
                return
            rclpy.spin_once(self, timeout_sec=0.1)

    def tick(self):
        t = (self.get_clock().now() - self.t0).nanoseconds / 1e9
        msg = Twist()
        if t < DRIVE_SECONDS:
            msg.linear.x = FORWARD_SPEED
        self.pub.publish(msg)
        if t >= DRIVE_SECONDS + 0.5:
            self.get_logger().info('done, stopping')
            raise SystemExit


def main(args=None):
    rclpy.init(args=args)
    node = DriveTest()
    try:
        rclpy.spin(node)
    except SystemExit:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
