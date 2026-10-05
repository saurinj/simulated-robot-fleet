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

echo
echo "===== HARNESS REPORT ====="
printf '%s\n' "${RESULTS[@]}"
echo "--------------------------"
echo "$PASS passed, $FAIL failed"
exit "$FAIL"
