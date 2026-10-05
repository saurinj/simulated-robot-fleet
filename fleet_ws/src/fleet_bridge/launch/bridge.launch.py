#!/usr/bin/env python3
"""Launch the telemetry bridge.

Usage:
    ros2 launch fleet_bridge bridge.launch.py                 # 5 robots (default)
    ros2 launch fleet_bridge bridge.launch.py num_robots:=10

Run the robot fleet in another terminal first:
    ros2 launch fleet_bot fleet.launch.py
"""

from launch import LaunchContext, LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _make_bridge(context: LaunchContext):
    n = int(LaunchConfiguration('num_robots').perform(context))
    robot_ids = [f'robot_{i}' for i in range(1, n + 1)]
    return [
        Node(
            package='fleet_bridge',
            executable='bridge_node',
            name='telemetry_bridge',
            parameters=[{'robot_ids': robot_ids}],
            output='screen',
        )
    ]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument(
            'num_robots',
            default_value='5',
            description='Number of robots; must match the fleet launch'),
        OpaqueFunction(function=_make_bridge),
    ])
