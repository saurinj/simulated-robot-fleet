#!/usr/bin/env python3
import rclpy
from nav2_simple_commander.robot_navigator import BasicNavigator, TaskResult
from geometry_msgs.msg import PoseStamped


def main():
    rclpy.init()
    nav = BasicNavigator()
    nav.waitUntilNav2Active()

    goal = PoseStamped()
    goal.header.frame_id = 'map'
    goal.header.stamp = nav.get_clock().now().to_msg()
    goal.pose.position.x = 2.0
    goal.pose.position.y = 0.0
    goal.pose.orientation.w = 1.0

    nav.goToPose(goal)
    while not nav.isTaskComplete():
        fb = nav.getFeedback()
        if fb:
            print(f'distance remaining: {fb.distance_remaining:.2f} m', flush=True)

    result = nav.getResult()
    print('SUCCEEDED' if result == TaskResult.SUCCEEDED else f'ENDED: {result}')
    rclpy.shutdown()


if __name__ == '__main__':
    main()
