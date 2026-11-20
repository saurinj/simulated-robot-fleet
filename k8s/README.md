# Fleet Ops on Kubernetes

The whole platform — Kafka, DDS discovery server, robot fleet, bridge,
dashboard, Prometheus, Grafana — running in a local
[kind](https://kind.sigs.k8s.io/) cluster.

## Architecture

```
                    ┌──────────────────────────────────────────────┐
 kind cluster       │  namespace: fleet                            │
  (namespace fleet) │                                              │
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

Pods can't rely on DDS multicast, so every ROS node registers with the
Fast DDS Discovery Server (`ROS_DISCOVERY_SERVER=discovery-server:11811`)
instead of using Simple Discovery. This is the standard ROS 2 pattern for
Kubernetes and other non-multicast networks.

Observability is the standard pull model: Prometheus scrapes the bridge's
`:8001/metrics` every 15s (via the `bridge-metrics` Service); Grafana only
talks to Prometheus, via PromQL. Five alert rules ship with Prometheus
(BridgeDown, TelemetryDropping, TelemetryFailing, TelemetryStopped,
QueueBackingUp) — visible in the Prometheus UI under Status → Rules.
Firing alerts go to Alertmanager (`alertmanager.yaml`), which pushes them
to a phone via an ntfy webhook, grouped by alert name, with resolved
notifications. The webhook URL is read from a Kubernetes Secret
(`url_file`), so it never lands in the repo. See `../METRICS.md` for the
outage drill that verified the path end to end.

## Prerequisites

- Docker Desktop, `kind`, `kubectl`
- Stop the old dashboard first (`:8000` is reused by the port-forward below).
  The docker-compose Kafka and dev-container fleet can stay or go — the
  cluster is self-contained.

## Runbook

```bash
cd simulated-robot-fleet   # repo root

# 1. Cluster
kind create cluster --config k8s/kind-cluster.yaml --name fleet

# 2. Images (fleet-ros bakes the colcon workspace; dashboard reuses its Dockerfile)
docker build -t fleet-ros:latest -f k8s/ros-image.Dockerfile .
docker build -t fleet-dashboard:latest ./dashboard
kind load docker-image fleet-ros:latest fleet-dashboard:latest --name fleet

# 3. Deploy (namespace, Kafka, topics job, discovery server, fleet, bridge,
#    dashboard, Prometheus, Grafana)
kubectl apply -k k8s/

# 4. Verify
kubectl get pods -n fleet -w
# kafka-0 running, create-topics completed, the rest running.
kubectl logs -n fleet deploy/bridge | grep -E "bridge online|stats"

# 5. Dashboard
kubectl port-forward -n fleet svc/dashboard 8000:8000
# open http://localhost:8000 — inject a fault, watch it latch, clear it.

# 6. Observability
kubectl port-forward -n fleet svc/prometheus 9090:9090 &
kubectl port-forward -n fleet svc/grafana 3000:3000 &
# Prometheus UI: http://localhost:9090
#   Status -> Targets: the fleet-bridge job should be UP (1/1).
#   Status -> Rules: the five fleet-bridge alert rules.
#   Graph: try  rate(fleet_bridge_telemetry_forwarded_total[1m])
# Grafana: http://localhost:3000  (admin/admin)
#   The "Fleet Bridge — Pipeline Health" dashboard is auto-provisioned.
#
# Demo the failure signals: scale Kafka to 0 and watch
#   rate(fleet_bridge_telemetry_failed_total[1m]){stage="delivery_error"}
# climb, TelemetryStopped and TelemetryFailing fire (phone push via
# Alertmanager), then scale it back and watch recovery and the resolved
# notifications.
#   kubectl -n fleet scale statefulset kafka --replicas=0
#   kubectl -n fleet scale statefulset kafka --replicas=1
```

## Teardown

```bash
kind delete cluster --name fleet
```

## Troubleshooting

- **ImagePullBackOff on `fleet-ros`/`fleet-dashboard`:** you forgot
  `kind load docker-image`. The manifests set
  `imagePullPolicy: IfNotPresent` because `:latest` otherwise defaults to
  `Always` (Docker Hub) — but the image still has to exist on the node.
- **Bridge logs show no telemetry / robots not discovered:** DDS discovery
  issue. Check the discovery server is up
  (`kubectl logs -n fleet deploy/discovery-server`), and that fleet/bridge
  pods have `ROS_DISCOVERY_SERVER=discovery-server:11811`. If the DNS name
  doesn't resolve for Fast DDS, the fallback is pointing the env var at the
  Service's ClusterIP.
- **`create-topics` stuck:** it waits for Kafka itself; check
  `kubectl logs -n fleet kafka-0`.
- **Two dashboards / double telemetry:** the old compose/dev-container stack
  is still running somewhere. `kubectl` shows only the cluster's pods —
  check your other terminals.
