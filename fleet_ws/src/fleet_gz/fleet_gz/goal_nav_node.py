#!/usr/bin/env python3
"""RobotNode: goal-seeking driver that reaches goal (the 'brain' under test).

Subscribes to /odom, publishes /cmd_vel at 10 Hz. Drives forward at
0.25 m/s until goal_x, goal_y are achieved, then stops by
publishing zero velocity continuously.

This node contains the AUTONOMY BEHAVIOR. It is the code under test.
The test harness (goal_check) observes from the outside and asserts.
RobotNode knows nothing about tests, pass bands, or timeouts.
"""

import rclpy
from rclpy.node import Node
from nav_msgs.msg import Odometry
from geometry_msgs.msg import Twist, Vector3

FORWARD_SPEED = 0.25      # m/s
PUBLISH_HZ = 10.0


class GoalRobotNode(Node):
    def __init__(self):
        super().__init__('goal_robot_node')
        self.latest_x = None

        self.declare_parameter('goal_x', 5.0)
        self.declare_parameter('goal_y', 0.0)

        self.create_subscription(Odometry, '/odom', self.on_odom, 10)
        self.cmd_pub = self.create_publisher(Twist, '/cmd_vel', 10)
        self.create_timer(1.0 / PUBLISH_HZ, self.tick)
        self.get_logger().info(
            f'GoalRobotNode: driving at {FORWARD_SPEED} m/s until '
            f'to x={self.get_parameter("goal_x").value}')

    def on_odom(self, msg: Odometry):
            self.latest_x = msg.pose.pose.position.x

    def tick(self):
        if self.latest_x is None:
            return
        
        goal_x = self.get_parameter('goal_x').value
        speed = FORWARD_SPEED if self.latest_x < goal_x else 0.0

        self.cmd_pub.publish(Twist(linear=Vector3(x=speed)))

def main():
    rclpy.init()
    node = GoalRobotNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
