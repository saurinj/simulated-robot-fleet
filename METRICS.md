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

## What's next (after the RAM upgrade, with Kubernetes)

1. Rebuild `fleet-ros:latest` — the Dockerfile now installs
   `prometheus_client`, and `bridge.yaml` declares `containerPort: 8001`
   (name `metrics`).
2. Deploy Prometheus with a scrape config (or ServiceMonitor) targeting
   the bridge's `metrics` port, and Grafana with a dashboard built on
   these metrics. Suggested first panels:
   - `rate(fleet_bridge_telemetry_forwarded_total[1m])` — pipeline throughput
   - `fleet_bridge_queue_depth` — backpressure early warning
   - `rate(fleet_bridge_telemetry_dropped_total[1m])` and
     `rate(fleet_bridge_telemetry_failed_total[1m])` — loss signals
   - `rate(fleet_bridge_commands_invalid_total[1m]) by (reason)` —
     bad-actor / bad-client detection on the command path
3. Alert rules: queue depth growing, drop rate > 0, any
   `commands_invalid{reason="unknown_robot"}` (someone probing the fleet).
