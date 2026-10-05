#!/usr/bin/env python3
"""Republish /odom pose as TF (odom -> base_link).

Foxglove's 3D panel needs the TF tree to place the robot in its scene, but
the starter world has no robot_state_publisher/URDF, so nothing publishes TF.
This relay subscribes to /odom and re-announces each pose as a transform.
It is scaffolding: once the URDF + robot_state_publisher step lands, this
node gets deleted.
"""
import rclpy
from rclpy.node import Node
from nav_msgs.msg import Odometry
from geometry_msgs.msg import TransformStamped
from tf2_ros import TransformBroadcaster


class OdomTfRelay(Node):
    def __init__(self):
        super().__init__('odom_tf_relay')
        self.br = TransformBroadcaster(self)
        self.sub = self.create_subscription(Odometry, '/odom', self.cb, 10)

    def cb(self, msg: Odometry):
        t = TransformStamped()
        t.header.stamp = msg.header.stamp
        t.header.frame_id = 'odom'
        t.child_frame_id = 'base_link'
        t.transform.translation.x = msg.pose.pose.position.x
        t.transform.translation.y = msg.pose.pose.position.y
        t.transform.translation.z = msg.pose.pose.position.z
        t.transform.rotation = msg.pose.pose.orientation
        self.br.sendTransform(t)


def main(args=None):
    rclpy.init(args=args)
    node = OdomTfRelay()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
