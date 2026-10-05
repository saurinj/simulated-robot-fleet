# Project 2 starter — Gazebo + ROS 2

Headless Gazebo Fortress (the release paired with ROS 2 Humble) running a
one-robot differential-drive world, bridged to ROS 2. This is the simulation
substrate Project 2 (the fleet regression test harness) will be built on.

No GUI anywhere: the sim runs server-only and visualization goes through
Foxglove in the browser. Nothing here needs the RAM upgrade — the headless
sim is a few hundred MB.

## Install (inside the dev container)

```bash
bash scripts/install-gz-deps.sh
ign gazebo --version   # expect: 6.x (Fortress)
```

## Build

```bash
cd /root/fleet_ws
colcon build --packages-select fleet_gz
source /root/fleet_ws/install/setup.bash
```

## Run

Terminal 1 — sim + bridge:

```bash
source /root/fleet_ws/install/setup.bash
ros2 launch fleet_gz bringup.launch.py
```

You should see `ign gazebo` start and the bridge report both topics.

Terminal 2 — scripted drive (no keyboard needed):

```bash
source /root/fleet_ws/install/setup.bash
ros2 run fleet_gz drive_test
```

Terminal 3 — watch it move:

```bash
source /root/fleet_ws/install/setup.bash
ros2 topic echo /odom
```

`pose.pose.position.x` should grow to ~0.9 m over the 3 s drive, then stop.
That single observation proves the whole loop: ROS 2 → bridge → Gazebo
physics → bridge → ROS 2.

Manual driving instead:

```bash
ros2 run teleop_twist_keyboard teleop_twist_keyboard
```

## Optional: see it in Foxglove

```bash
# forward port 8765 from the container (VS Code Ports tab), then:
ros2 launch foxglove_bridge foxglove_bridge_launch.xml port:=8765
```

Open https://app.foxglove.dev → "Open connection" → `ws://localhost:8765`,
add an Odometry panel on `/odom`.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `ign: command not found` | gz-fortress not installed; re-run `scripts/install-gz-deps.sh`, then `ign gazebo --version` should print 6.x |
| Bridge starts but `/odom` never appears | sim paused — the launch passes `-r`; if you ran `ign gazebo` by hand, press play or add `-r` |
| `ros2 topic list` shows nothing new | unsourced terminal — every terminal needs `source /root/fleet_ws/install/setup.bash` |
| Robot doesn't move on `/cmd_vel` | bridge direction mixup — check `config/bridge.yaml` (`cmd_vel` must be ROS_TO_GZ) |
| `ign gazebo` can't find the world | `FindPackageShare('fleet_gz')` — rebuild + re-source after editing worlds |

## What's next (the ladder)

1. **TF**: bridge Gazebo poses to `/tf` so Foxglove can render the robot frame.
2. **Lidar**: add a `ignition-gazebo-sensors-system` lidar to diff_bot, bridge
   `gz.msgs.LaserScan` → `sensor_msgs/msg/LaserScan`, view the scan in Foxglove.
3. **Scenario world**: a corridor-with-obstacles SDF as the first "test case".
4. **The harness**: launch scenario → inject fault (reuse the OTA fault pattern
   from the fleet project) → assert on `/odom` + telemetry → write a
   pass/fail report. That's Project 2 proper.
