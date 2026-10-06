# Simulated Robot Fleet — Telemetry & Operations Platform
![Harness](https://github.com/saurinj/simulated-robot-fleet/actions/workflows/harness.yml/badge.svg)

A production-shaped robotics fleet telemetry platform: five simulated ROS 2 robots
streaming telemetry through a Kafka-backed bridge, deployed on Kubernetes, with
Prometheus/Grafana observability and a live operations dashboard.

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

## What's demonstrated

- **End-to-end telemetry pipeline** — 5 robots publishing at a combined ~40 msgs/s,
  bridged into Kafka with zero drops (verified via bridge counters and Grafana).
- **OTA config push** — `CMD_SET_PARAM` with a robot-side allowlist and range
  clamps (`publish_rate_hz`, `fault_probability`, `recover_probability`);
  `robot_id` is deliberately not tunable.
- **Fault injection → alert → clear round-trips** — inject a fault from the
  dashboard, watch the alert latch, clear it, watch recovery, all live.
- **Chaos-tested** — the measured blast radius (~2–3 min absorbed; ~4 min exhausts the retry budget; delivery_error counted by stage).
- **Kubernetes-native** — kind cluster, KRaft Kafka StatefulSet with persistent
  volume, topics Job, discovery server, Prometheus scrape + 5 alert rules
  (BridgeDown, TelemetryDropping, TelemetryFailing, TelemetryStopped, QueueBackingUp),
  provisioned Grafana dashboard.
- **Measured, not assumed** — 7 Prometheus metrics on the bridge
  (forwarded/dropped/failed counters, queue-depth gauge, DLQ + command counters);
  the bridge's `forwarded` counter is the data-plane oracle.
- **Regression harness** — run_harness.sh owns the sim lifecycle and asserts on physical outcomes, not commands sent: lidar sees the obstacle, the robot actually moved ~0.9m. 2 passed, 0 failed.

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
| `fleet_ws/src/fleet_gz` | Gazebo simulation package (sister project: regression harness) |
| `dashboard/` | Fleet Ops web UI (FastAPI + static frontend) |
| `k8s/` | kind config, Kubernetes manifests, K8s runbook (`k8s/README.md`) |
| `docker-compose.yml` | Legacy compose setup (pre-Kubernetes) |

## Docs

- `k8s/README.md` — Kubernetes runbook: architecture, deploy, verify, chaos demo
- `METRICS.md` — Prometheus metrics catalog
- `OTA_CONFIG.md` — OTA config-push design (commands, allowlist, clamps)
- `GZ_STARTER.md` — Gazebo simulator starter (regression-harness project)

## Stack

ROS 2 Humble · Gazebo Fortress · Apache Kafka 3.7 (KRaft) · kind / Kubernetes ·
Prometheus · Grafana · FastAPI · Docker
