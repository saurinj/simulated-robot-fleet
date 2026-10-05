#!/usr/bin/env bash
#
# Install Gazebo Fortress (the release paired with ROS 2 Humble) plus the
# ros_gz bridge, teleop_twist_keyboard, and the Foxglove bridge.
#
# Run INSIDE the dev container. Idempotent: safe to re-run.
set -euo pipefail

SUDO=""
[ "$(id -u)" -ne 0 ] && SUDO="sudo"
command -v curl >/dev/null || $SUDO apt-get install -y curl

if [ ! -f /etc/apt/sources.list.d/gazebo-stable.list ]; then
  echo "Adding OSRF Gazebo apt repository..."
  $SUDO curl -fsSL https://packages.osrfoundation.org/gazebo.gpg \
    -o /usr/share/keyrings/pkgs-osrf-archive-keyring.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/pkgs-osrf-archive-keyring.gpg] \
http://packages.osrfoundation.org/gazebo/ubuntu-stable $(lsb_release -cs) main" \
    | $SUDO tee /etc/apt/sources.list.d/gazebo-stable.list > /dev/null
  $SUDO apt-get update
fi

$SUDO apt-get install -y \
  gz-fortress \
  ros-humble-ros-gz \
  ros-humble-teleop-twist-keyboard \
  ros-humble-foxglove-bridge

echo "---"
ign gazebo --version
echo "Gazebo Fortress + ros_gz ready."
