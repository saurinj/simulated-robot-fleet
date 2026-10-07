#!/usr/bin/env bash
# Project 2 regression harness (seed).
# Owns the full lifecycle: start sim -> run checks -> report -> tear down.
# Exit code = number of failed checks.
set -o pipefail
cd /root/fleet_ws
source install/setup.bash

PASS=0; FAIL=0
RESULTS=()

pkill -f "ign gazebo" 2>/dev/null
pkill -f "parameter_bridge" 2>/dev/null
sleep 1

cleanup() {
  kill "$LAUNCH_PID" 2>/dev/null
  sleep 2
  pkill -f "ign gazebo" 2>/dev/null
  pkill -f "parameter_bridge" 2>/dev/null
  pkill -f "bringup.launch" 2>/dev/null
  pkill -f "corridor_robot_node" 2>/dev/null
  pkill -f "goal_nav_node" 2>/dev/null
  pkill -f "goal_check" 2>/dev/null
  pkill -f "odom_tf_relay" 2>/dev/null
  pkill -f "goal_steer_node" 2>/dev/null
  sleep 2
}
trap cleanup EXIT

ros2 launch fleet_gz bringup.launch.py > /tmp/harness-bringup.log 2>&1 &
LAUNCH_PID=$!

wait_for_data() {  # $1 = topic
  echo "waiting for data on $1 ..."
  for i in $(seq 1 12); do
    if timeout 10 ros2 topic echo "$1" --once >/dev/null 2>&1; then
      echo "$1 flowing"
      return 0
    fi
  done
  echo "FAIL: no data on $1 after ~2 min (see /tmp/harness-bringup.log)"
  return 1
}

wait_for_data /scan || exit 2
wait_for_data /odom || exit 2

run_check() {
  local name=$1; shift
  echo "--- $name ---"
  if "$@"; then
    RESULTS+=("PASS  $name"); PASS=$((PASS + 1))
  else
    RESULTS+=("FAIL  $name"); FAIL=$((FAIL + 1))
  fi
}

# perception first: the world must be pristine for the assertion
run_check "scan_check (perception)" ros2 run fleet_gz scan_check
run_check "drive_check (motion)"    ros2 run fleet_gz drive_check

# --- Phase 2: corridor (brain + examiner) ---
echo
echo "--- Phase 2: corridor_world.sdf ---"

# Tear down Phase 1 sim.
kill "$LAUNCH_PID" 2>/dev/null
sleep 2
pkill -f "ign gazebo" 2>/dev/null
pkill -f "parameter_bridge" 2>/dev/null
sleep 2

# Launch corridor world.
ros2 launch fleet_gz bringup.launch.py world:=corridor_world.sdf > /tmp/harness-bringup-corridor.log 2>&1 &
LAUNCH_PID=$!

wait_for_data /scan || exit 2
wait_for_data /odom || exit 2

# Start the brain in background.
ros2 run fleet_gz corridor_robot_node --ros-args -p use_sim_time:=True &
BRAIN_PID=$!
sleep 3  # let it start driving

# Examiner: exit code is the verdict.
run_check "stop_check (corridor lidar-gated stop)" ros2 run fleet_gz stop_check --ros-args -p use_sim_time:=True

# Stop the brain.
pkill -f "corridor_robot_node" 2>/dev/null
sleep 2

# --- Phase 3: goal_world.sdf (navigation) ---
echo
echo "--- Phase 3: goal_world.sdf (only x axis movement) ---"

# Tear down Phase 2 sim.
kill "$LAUNCH_PID" 2>/dev/null
sleep 2
pkill -f "ign gazebo" 2>/dev/null
pkill -f "parameter_bridge" 2>/dev/null
sleep 2

# Launch goal world.
ros2 launch fleet_gz bringup.launch.py world:=goal_world.sdf > /tmp/harness-bringup-goal.log 2>&1 &
LAUNCH_PID=$!

wait_for_data /scan || exit 2
wait_for_data /odom || exit 2

# Start the brain in background.
ros2 run fleet_gz goal_nav_node --ros-args -p use_sim_time:=True -p goal_x:=5.0 -p goal_y:=0.0 &
BRAIN_PID=$!
sleep 3

# Examiner: exit code is the verdict.
run_check "goal_check (navigation to goal)" ros2 run fleet_gz goal_check --ros-args -p use_sim_time:=True -p goal_x:=5.0 -p goal_y:=0.0

# Stop the brain.
pkill -f "goal_nav_node" 2>/dev/null
sleep 2

# --- Phase 4: goal_world.sdf (steering navigation) ---
echo
echo "--- Phase 4: goal_world.sdf (steering - both X and Y axis movement) ---"

# Tear down Phase 3 sim.
kill "$LAUNCH_PID" 2>/dev/null
sleep 2
pkill -f "ign gazebo" 2>/dev/null
pkill -f "parameter_bridge" 2>/dev/null
sleep 2

# Launch goal world.
ros2 launch fleet_gz bringup.launch.py world:=goal_world.sdf > /tmp/harness-bringup-steer.log 2>&1 &
LAUNCH_PID=$!

wait_for_data /scan || exit 2
wait_for_data /odom || exit 2

# Start the steering brain in background.
ros2 run fleet_gz goal_steer_node --ros-args -p use_sim_time:=True -p goal_x:=3.0 -p goal_y:=3.0 &
sleep 3

# Examiner: exit code is the verdict.
run_check "goal_steer_check (diagonal navigation)" ros2 run fleet_gz goal_check --ros-args -p use_sim_time:=True -p goal_x:=3.0 -p goal_y:=3.0

# Stop the brain.
pkill -f "goal_steer_node" 2>/dev/null
sleep 1

echo
echo "===== HARNESS REPORT ====="
printf '%s\n' "${RESULTS[@]}"
echo "--------------------------"
echo "$PASS passed, $FAIL failed"
exit "$FAIL"
