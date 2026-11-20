# Simulated Robot Fleet — Telemetry & Operations Platform
![Harness](https://github.com/saurinj/simulated-robot-fleet/actions/workflows/harness.yml/badge.svg)

A production-shaped robotics fleet platform, built in three parts:

1. **Fleet telemetry and operations** — five simulated ROS 2 robots streaming
   telemetry through a Kafka-backed bridge on Kubernetes, with OTA config push,
   Prometheus/Grafana/Alertmanager observability and a live operations dashboard.
2. **Simulation regression harness** — Gazebo scenarios in GitHub Actions that
   assert what the robot physically did, not which commands were sent.
3. **Multi-robot coordination and navigation** *(in progress)* — a 3-robot
   Gazebo fleet with yield logic, and Nav2 + SLAM Toolbox on TurtleBot3.

Built as a portfolio project for a transition into **robotics fleet infrastructure**
— the emphasis throughout is on reliability, observability, and measurable behavior,
not demos.

## Architecture

```
                        ┌──────────────────────────────────────────────┐
 kind cluster           │  namespace: fleet                            │
                        │                                              │
                        │  ┌─────────┐   ┌──────────────────┐           │
                        │  │  fleet  │   │ discovery-server │           │
                        │  │5 robots │──▶│  (Fast DDS, :11811)│          │
                        │  └────┬────┘   └──────────────────┘           │
                        │       │ DDS (via discovery server)           │
                        │  ┌────▼────┐    ┌───────┐    ┌───────────┐    │
                        │  │ bridge  │───▶│ kafka │◀───│ dashboard │    │
                        │  └────┬────┘    │(KRaft)│    │ (:8000)   │    │
                        │       │ :8001   └───────┘    └───────────┘    │
                        │       │ /metrics (pull)                      │
                        │  ┌────▼────────┐      ┌──────────┐            │
                        │  │ prometheus  │─────▶│ grafana  │            │
                        │  │ (:9090)     │PromQL│ (:3000)  │            │
                        │  └─────────────┘      └──────────┘            │
                        └──────────────────────────────────────────────┘
```

Two paths through the system:

- **Telemetry:** robots → DDS → bridge → Kafka (`fleet.telemetry`) → dashboard/alerts
- **Commands:** dashboard → Kafka (`fleet.commands`) → bridge → robots

Pods can't rely on DDS multicast, so every ROS node registers with the Fast DDS
Discovery Server instead of using Simple Discovery — the standard ROS 2 pattern
for Kubernetes.

## Part 1 — Fleet telemetry and operations

- **End-to-end telemetry pipeline** — 5 robots publishing at a combined ~40 msgs/s,
  bridged into Kafka with zero drops (verified via bridge counters and Grafana).
- **OTA config push** — `CMD_SET_PARAM` with a robot-side allowlist and range
  clamps (`publish_rate_hz`, `fault_probability`, `recover_probability`);
  `robot_id` is deliberately not tunable. Design in [`OTA_CONFIG.md`](OTA_CONFIG.md).
- **Fault injection → alert → clear round-trips** — inject a fault from the
  dashboard, watch the alert latch, clear it, watch recovery, all live.
- **Chaos-tested** — Kafka outages of ~2–3 min are absorbed; ~4 min exhausts the
  retry budget; failures are counted by stage (`send_error` vs `delivery_error`).
- **Kubernetes-native** — kind cluster, KRaft Kafka StatefulSet with persistent
  volume, topics Job, discovery server, Prometheus scrape + 5 alert rules
  (BridgeDown, TelemetryDropping, TelemetryFailing, TelemetryStopped, QueueBackingUp),
  provisioned Grafana dashboard.
- **Alerts reach a human** — Prometheus → Alertmanager → ntfy webhook → phone,
  grouped by alert, with resolved notifications; the webhook URL lives in a
  Kubernetes Secret, never in the repo. A Kafka-outage drill (2026-10-15) showed
  TelemetryStopped and TelemetryFailing firing and resolving end to end
  (sequence diagram in [`METRICS.md`](METRICS.md)).
- **Measured, not assumed** — 7 Prometheus metrics on the bridge
  (forwarded/dropped/failed counters, queue-depth gauge, DLQ + command counters),
  kept fleet-level to avoid label-cardinality blowup; the bridge's `forwarded`
  counter is the data-plane oracle.

## Part 2 — Simulation regression harness

`fleet_ws/scripts/run_harness.sh` owns the whole sim lifecycle — start Gazebo
(headless), run a brain, run an independent examiner, tear down — and its exit
code is the number of failed checks. It runs on every push via
[GitHub Actions](.github/workflows/harness.yml) in the `osrf/ros:humble-desktop`
container.

Each check asserts a **physical outcome**, not a command sent:

| Phase | World | Check | Passes when |
|---|---|---|---|
| 1 | default | `scan_check` | Lidar sees the obstacle in front of the robot |
| 1 | default | `drive_check` | The robot actually moved (~0.9 m, from odometry) |
| 2 | `corridor_world` | `stop_check` | The robot stops before the wall, gated on lidar |
| 3 | `goal_world` | `goal_check` | Drive-to-goal stops within 0.5 m of the goal |
| 4 | `goal_world` | `goal_check` (diagonal) | Proportional steering reaches a goal off both axes |
| 5 | `goal_with_obstacle_world` | `obstacle_check` | The avoidance logic fires: the robot meets the obstacle and turns away |
| 6 | `fleet_world` | `fleet_check` | *In progress, non-blocking in CI* — 3 robots reach their goals without colliding |

**Phases 1–5: 6 checks passing and gating CI.** Phase 6 runs and reports but doesn't fail the build while the robot geometry is tuned for the 3-robot run. The robot "brains" are kept separate from the
examiners (brain drives, examiner judges), so a check can't pass just because the
brain thinks it succeeded. The v3 brain also has a sensor-dropout failsafe: it
stops if lidar or odometry goes stale for over 1 s.

Design notes from building it:

- **Lidar index 0 points behind the robot** — the first stop check was measuring
  the rear wedge. The brains now find the forward sector from the scan's own
  `angle_min`/`angle_increment` instead of assuming an index convention.
- **Measured before choosing a robot body** — a custom 4-wheel bot showed 2.36×
  odometry slip and 16° pitch; TurtleBot3 measured 0.96×, so the harness moved to it.

## Part 3 — Multi-robot and navigation *(in progress)*

- **Fleet in Gazebo** — 3 namespaced robots (`/robot1`, `/robot2`, ...) in
  `fleet_world.sdf`, a `FleetAwareRobotNode` that yields to nearby peers, and a
  fleet examiner (`fleet_check`). Convergence is still being tuned.
- **Nav2 + SLAM Toolbox on TurtleBot3** — map built with SLAM Toolbox
  (`maps/obstacle_world.*`); Nav2 goal navigation (`scripts/nav2_goal.py`) is
  being tuned (DWB controller and TF remapping).

## Quickstart

Prerequisites: Docker Desktop (8 GB), `kind`, `kubectl`.

```bash
kind create cluster --config k8s/kind-cluster.yaml --name fleet

docker build -t fleet-ros:latest -f k8s/ros-image.Dockerfile .
docker build -t fleet-dashboard:latest ./dashboard
kind load docker-image fleet-ros:latest fleet-dashboard:latest --name fleet

kubectl apply -k k8s/

# Watch it come up: kafka-0 Running, create-topics Completed, rest Running
kubectl get pods -n fleet

# Fleet Ops dashboard (inject faults, push config, watch alerts)
kubectl port-forward -n fleet svc/dashboard 8000:8000
# → http://localhost:8000

# Observability
kubectl port-forward -n fleet svc/prometheus 9090:9090 &
kubectl port-forward -n fleet svc/grafana 3000:3000 &
# Prometheus: http://localhost:9090 (Status → Targets, Rules)
# Grafana:    http://localhost:3000 (admin/admin) — "Fleet Bridge — Pipeline Health"
```

Verify the data plane:

```bash
kubectl logs -n fleet deploy/bridge | grep -E "stats:" | tail -3
# forwarded>0 means telemetry is flowing
```

## Repository layout

| Path | What it is |
|---|---|
| `fleet_ws/src/fleet_bot` | Robot simulator nodes (telemetry, faults, OTA params) |
| `fleet_ws/src/fleet_bridge` | DDS↔Kafka bridge with Prometheus instrumentation |
| `fleet_ws/src/fleet_msgs` | Custom ROS 2 message definitions |
| `fleet_ws/src/fleet_gz` | Gazebo worlds, robot brains and examiners for the regression harness; Nav2/SLAM config |
| `fleet_ws/scripts/` | `run_harness.sh` (harness runner), fleet bring-up, Nav2 goal script |
| `.github/workflows/harness.yml` | CI: builds the workspace and runs the harness on every push |
| `dashboard/` | Fleet Ops web UI (FastAPI + static frontend) |
| `k8s/` | kind config, Kubernetes manifests, K8s runbook (`k8s/README.md`) |
| `docker-compose.yml` | Legacy compose setup (pre-Kubernetes) |

## Docs

- [`k8s/README.md`](k8s/README.md) — Kubernetes runbook: architecture, deploy, verify, chaos demo
- [`METRICS.md`](METRICS.md) — Prometheus metrics catalog, alerting path and the outage drill
- [`OTA_CONFIG.md`](OTA_CONFIG.md) — OTA config-push design (commands, allowlist, clamps, delivery semantics)
- [`GZ_STARTER.md`](GZ_STARTER.md) — Gazebo simulator starter (regression-harness project)

## Stack

ROS 2 Humble · Gazebo Fortress · Nav2 · SLAM Toolbox · Apache Kafka 3.7 (KRaft) ·
kind / Kubernetes · Prometheus · Grafana · Alertmanager · FastAPI · Docker ·
GitHub Actions
