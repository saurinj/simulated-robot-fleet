#!/bin/bash
# Project 3 fleet bringup: static TF publishers + 3 brains
# Assumes Gazebo (fleet_world.sdf) and ros_gz_bridge are already running.
# Edit SPAWN_* to match your SDF spawn poses if they differ.

set -e
NO_WAIT=false
[[ "$1" == "--no-wait" ]] && NO_WAIT=true

source /opt/ros/humble/setup.bash
source /root/fleet_ws/install/setup.bash

# Robot configs: name | goal_x | goal_y | spawn_x | spawn_y | spawn_yaw
ROBOTS=(
  "robot1 4.0 4.0 0 0 0"
  "robot2 -4.0 1.0 0 3 0"
  "robot3 1.0 -4.0 3 0 0"
)
# Gazebo model names (for lidar frames)
MODELS=("diff_bot_1" "diff_bot_2" "diff_bot_3")
# Lidar mount offset from SDF (x y z roll pitch yaw)
LIDAR_XYZRPY="0.15 0 0.23 0 0 0"

PIDS=()
cleanup() {
  echo "Stopping fleet..."
  for pid in "${PIDS[@]}"; do kill "$pid" 2>/dev/null || true; done
  pkill -f static_transform_publisher 2>/dev/null || true
  pkill -f goal_steer_node 2>/dev/null || true
}
trap cleanup EXIT INT TERM

i=0
for entry in "${ROBOTS[@]}"; do
  read -r name gx gy sx sy syaw <<< "$entry"
  model="${MODELS[$i]}"

  # map -> robotN/odom (static, spawn pose)
  ros2 run tf2_ros static_transform_publisher \
    "$sx" "$sy" 0 0 0 "$syaw" map "$name/odom" &
  PIDS+=($!)

  # robotN/base_link -> lidar (static, sensor mount)
  # shellcheck disable=SC2086
  ros2 run tf2_ros static_transform_publisher \
    $LIDAR_XYZRPY "$name/base_link" "$model/base_link/lidar" &
  PIDS+=($!)

  # brain with explicit topic remaps (code uses absolute /scan etc.)
  ros2 run fleet_gz fleet_aware_robot_node --ros-args \
    -r __ns:="/$name" \
    -r /scan:="/$name/scan" \
    -r /odom:="/$name/odom" \
    -r /cmd_vel:="/$name/cmd_vel" \
    -p use_sim_time:=True \
    -p goal_x:="$gx" -p goal_y:="$gy" &
  PIDS+=($!)

  i=$((i + 1))
done

if [ "$NO_WAIT" = true ]; then
  echo "Fleet launched (backgrounded for harness)."
  trap - EXIT INT TERM
  exit 0
fi

echo "Fleet up: ${#ROBOTS[@]} robots. Ctrl-C to stop."
wait
