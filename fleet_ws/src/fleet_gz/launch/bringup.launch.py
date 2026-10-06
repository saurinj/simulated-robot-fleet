#!/usr/bin/env python3
"""Project 2 starter: headless Gazebo + ROS 2 bridge.

Launches:
  1. `ign gazebo` server-only (-s, no GUI -- this runs on a Mac via Docker, so
     there is no X11 to fight) and unpaused (-r), with test_world.sdf.
  2. ros_gz_bridge parameter_bridge using config/bridge.yaml, connecting
     Gazebo Transport topics to ROS 2 topics.
  3. odom_tf_relay, which republishes /odom as TF (odom -> base_link) so
     Foxglove's 3D panel can place the robot. Scaffolding until the URDF +
     robot_state_publisher step lands.

`ign gazebo` is launched directly (rather than through ros_gz_sim's
gz_sim.launch.py) so every argv entry is explicit -- no string-splitting
surprises with the gz_args launch argument.

Then, in other terminals (same container, workspace sourced):
  ros2 run fleet_gz drive_test      # scripted 3 s drive, no keyboard needed
  ros2 topic echo /odom             # watch pose.x grow while it drives
  ros2 run teleop_twist_keyboard teleop_twist_keyboard   # drive it manually
"""

from launch import LaunchDescription
from launch.actions import ExecuteProcess, DeclareLaunchArgument
from launch.substitutions import PathJoinSubstitution, LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    pkg_share = FindPackageShare('fleet_gz')
    world = PathJoinSubstitution([pkg_share, 'worlds', LaunchConfiguration('world')])
    bridge_config = PathJoinSubstitution([pkg_share, 'config', 'bridge.yaml'])

    gz_server = ExecuteProcess(
        cmd=['ign', 'gazebo', '-s', '-r', '-v', '2', world],
        output='screen',
    )

    bridge = Node(
        package='ros_gz_bridge',
        executable='parameter_bridge',
        parameters=[{'config_file': bridge_config}],
        output='screen',
    )

    tf_relay = Node(
        package='fleet_gz',
        executable='odom_tf_relay',
        output='screen',
    )

    return LaunchDescription([ DeclareLaunchArgument('world', default_value='test_world.sdf', 
                            description='SDF world file'), gz_server, bridge, tf_relay])
