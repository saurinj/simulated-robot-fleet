# Bridge Prometheus metrics

The bridge now exposes Prometheus metrics on `:8001/metrics` (port
configurable via the `metrics_port` ROS parameter). The endpoint is served
by `prometheus_client`'s built-in HTTP server on its own daemon thread, so
scraping never blocks the ROS executor, the Kafka sender thread, or the
command consumer thread.

Starting the metrics server is best-effort: a bind failure is logged as a
warning and the bridge keeps running. Metrics are observability, not the
data path.

## Metric catalog

Every metric mirrors one of the bridge's plain-int stats counters (which
remain the human-readable source in the 30s `stats:` log line).

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `fleet_bridge_telemetry_forwarded_total` | Counter | — | Telemetry messages acked by Kafka |
| `fleet_bridge_telemetry_dropped_total` | Counter | — | Dropped: internal queue full (backpressure) |
| `fleet_bridge_telemetry_failed_total` | Counter | `stage` | Lost to Kafka errors. `send_error` = `producer.send()` raised (buffer full/closing); `delivery_error` = broker ack failed after retries |
| `fleet_bridge_dlq_total` | Counter | `reason` | Routed to `fleet.telemetry.dlq`. `telemetry_serialize` = malformed ROS msg; `command_malformed` = malformed command doc |
| `fleet_bridge_queue_depth` | Gauge | — | Current depth of the ROS→Kafka queue (set on each 30s stats tick) |
| `fleet_bridge_commands_forwarded_total` | Counter | — | Commands forwarded Kafka→ROS |
| `fleet_bridge_commands_invalid_total` | Counter | `reason` | Rejected before ROS. `malformed` / `unknown_robot` / `invalid_code` |

Design notes:

- **No per-robot labels on high-frequency counters.** `robot_id` on a
  40 msg/s counter would explode series cardinality. Per-robot health
  stays in the dashboard; the bridge exports fleet-level pipeline health.
- **Queue depth is a gauge, not a counter.** The interesting signal is
  "is it growing?", which is what backpressure looks like.
- **Failed vs dropped are distinct.** Dropped = we chose to shed load
  (queue full). Failed = Kafka lost it. They need different runbooks.

## Verify it (dev container, current stack)

```bash
# inside the dev container
pip install prometheus_client
cd /root/fleet_ws && colcon build --packages-select fleet_bridge
source /root/fleet_ws/install/setup.bash
# restart the bridge however you normally launch it, then:
curl -s localhost:8001/metrics | grep fleet_bridge
```

Expected (values grow as traffic flows):

```
# HELP fleet_bridge_telemetry_forwarded_total Telemetry messages acked by Kafka
# TYPE fleet_bridge_telemetry_forwarded_total counter
fleet_bridge_telemetry_forwarded_total 1240.0
# HELP fleet_bridge_queue_depth Current depth of the ROS->Kafka telemetry queue
# TYPE fleet_bridge_queue_depth gauge
fleet_bridge_queue_depth 0.0
```

## Observability status (updated 2026-10-15)

The Kubernetes plan that used to sit here is complete. The stack runs
on a kind cluster (namespace `fleet`):

- **Prometheus** (v3.14.0) scrapes `bridge-metrics:8001` every 15s
  (job `fleet-bridge`) and keeps 7 days of samples.
- **Grafana** renders the provisioned "Fleet Bridge - Pipeline Health"
  dashboard. It stores no metrics — it queries Prometheus at view time.
- **Alert rules are canonical in Prometheus** (`rules.yml`, group
  `fleet-bridge`, in the `prometheus-config` ConfigMap): BridgeDown,
  TelemetryDropping, TelemetryFailing, TelemetryStopped,
  QueueBackingUp. Grafana-UI duplicates written during the survey were
  retired: they drifted from the tuned thresholds (queue 10 vs 1000)
  and Grafana's rule storage is ephemeral (no PVC).
- **Alertmanager** (v0.30.1, `k8s/alertmanager.yaml`) is the single
  notification path: Prometheus → Alertmanager → ntfy webhook → phone,
  grouped by alertname, with resolved notifications. The webhook URL
  lives in a cluster Secret read via `url_file` — never in this repo.
- **Verified end to end 2026-10-15** with a Kafka-outage drill:
  TelemetryStopped and TelemetryFailing fired from the canonical rules
  during the outage and resolved after recovery, phone pushes both ways.

```mermaid
sequenceDiagram
    autonumber
    actor Op as Saurin (operator)
    participant K as Kafka
    participant B as Bridge
    participant P as Prometheus
    participant A as Alertmanager
    participant S as K8s Secret
    participant N as ntfy.sh
    participant Ph as Phone

    rect rgb(224, 231, 255)
    Note over P,B: Steady state
    loop Every 15s
        P->>B: GET /metrics (bridge-metrics:8001)
        B-->>P: telemetry counters · queue depth
    end
    P->>P: Evaluate rules.yml — all Normal
    end

    rect rgb(254, 226, 226)
    Note over Op,K: Drill — fault injection (2026-10-15)
    Op->>K: kubectl scale sts kafka --replicas=0
    B->>K: telemetry send
    K--xB: delivery fails (stage=delivery_error)
    Note over B: failed_total climbs · forwarding stalls · queue backs up
    P->>P: TelemetryStopped fires 09:02:25 (critical)<br/>TelemetryFailing fires 09:02:55 (warning)
    P->>A: POST firing alerts
    A->>S: read webhook URL (url_file)
    A->>A: group by alertname · group_wait 10s
    A->>N: POST webhook (JSON)
    N->>Ph: push — Stopped 09:02 · Failing 09:03
    end

    rect rgb(220, 252, 231)
    Note over Op,K: Recovery
    Op->>K: kubectl scale sts kafka --replicas=1
    B->>K: reconnect — forwarding resumes · queue drains
    P->>P: conditions clear (Stopped endsAt 09:05:55)
    P->>A: POST resolved alerts
    A->>N: POST webhook (resolved)
    N->>Ph: push — resolved 09:07
    end

    Note over P,Ph: Grafana is not in this path — it only queries Prometheus to display state.

