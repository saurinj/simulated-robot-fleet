#!/usr/bin/env python3
"""Launch N simulated robots, each in its own namespace.

Usage:
    ros2 launch fleet_bot fleet.launch.py                       # 5 robots (default)
    ros2 launch fleet_bot fleet.launch.py num_robots:=10
    ros2 launch fleet_bot fleet.launch.py num_robots:=3 fault_probability:=0.01

Each robot publishes on /robot_<i>/telemetry and listens on /robot_<i>/command.
Namespaces are the core fleet pattern here: identical nodes, isolated topics,
distinguished purely by namespace + the robot_id parameter.
"""

from launch import LaunchContext, LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _make_robots(context: LaunchContext):
    n = int(LaunchConfiguration('num_robots').perform(context))
    fault_p = float(LaunchConfiguration('fault_probability').perform(context))

    nodes = []
    for i in range(1, n + 1):
        robot_id = f'robot_{i}'
        nodes.append(
            Node(
                package='fleet_bot',
                executable='robot_node',
                name='robot_node',
                namespace=robot_id,
                parameters=[{
                    'robot_id': robot_id,
                    'publish_rate_hz': 10.0,
                    'fault_probability': fault_p,
                    'recover_probability': 0.05,
                }],
                output='screen',
            )
        )
    return nodes


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument(
            'num_robots',
            default_value='5',
            description='Number of simulated robots to spawn'),
        DeclareLaunchArgument(
            'fault_probability',
            default_value='0.001',
            description='Per-publish-tick fault probability for each robot'),
        OpaqueFunction(function=_make_robots),
    ])
