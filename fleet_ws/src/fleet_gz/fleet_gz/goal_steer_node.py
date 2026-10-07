#!/usr/bin/env python3
"""RobotNode: goal-seeking driver that is an extension to previous version goal_nav_node. It reaches goal (the 'brain' under test) including Y axis.

Subscribes to /odom, publishes /cmd_vel at 10 Hz. Drives forward at
0.25 m/s until goal_x, goal_y are achieved, then stops by
publishing zero velocity continuously.

This node contains the AUTONOMY BEHAVIOR. It is the code under test.
The test harness (goal_check) observes from the outside and asserts.
RobotNode knows nothing about tests, pass bands, or timeouts.
"""

import math

import rclpy
from rclpy.node import Node
from nav_msgs.msg import Odometry
from geometry_msgs.msg import Twist, Vector3

FORWARD_SPEED = 0.25      # m/s
PUBLISH_HZ = 10.0


class GoalSteerNode(Node):
    def __init__(self):
        super().__init__('goal_steer_robot_node')
        self.latest_ori = None
        self.latest_pos = None

        self.declare_parameter('goal_x', 5.0)
        self.declare_parameter('goal_y', 0.0)

        self.create_subscription(Odometry, '/odom', self.on_odom, 10)
        self.cmd_pub = self.create_publisher(Twist, '/cmd_vel', 10)
        self.create_timer(1.0 / PUBLISH_HZ, self.tick)
        self.get_logger().info(
            f'GoalRobotNode: driving at {FORWARD_SPEED} m/s until '
            f'to x={self.get_parameter("goal_x").value}')

    def on_odom(self, msg: Odometry):
            self.latest_ori = msg.pose.pose.orientation
            self.latest_pos = msg.pose.pose.position

    def tick(self):
        if self.latest_ori is None or self.latest_pos is None:
            return
        q = self.latest_ori
        p = self.latest_pos
        goal_x = self.get_parameter('goal_x').value
        goal_y = self.get_parameter('goal_y').value

        dx = goal_x - p.x
        dy = goal_y - p.y

        dist = math.hypot(dx, dy)
        yaw = math.atan2(2*(q.w*q.z + q.x*q.y), 1 - 2*(q.y*q.y + q.z*q.z))
        target_heading = math.atan2(dy, dx)
        heading_error = target_heading - yaw
        # Wrap to [-pi, pi]:
        heading_error = (heading_error + math.pi) % (2*math.pi) - math.pi

        if abs(heading_error) > 0.3:
            # Turn in place
            cmd = Twist(linear=Vector3(x=0.0), angular=Vector3(z=1.0 * heading_error))
        elif dist > 0.3:
            # Drive forward, correcting heading
            cmd = Twist(linear=Vector3(x=FORWARD_SPEED), angular=Vector3(z=1.0 * heading_error))
        else:
            # Arrived
            cmd = Twist()

        self.cmd_pub.publish(cmd)

def main():
    rclpy.init()
    node = GoalSteerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
