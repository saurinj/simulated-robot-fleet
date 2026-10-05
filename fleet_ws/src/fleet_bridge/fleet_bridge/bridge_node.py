#!/usr/bin/env python3
"""Fleet bridge: ROS 2 <-> Kafka.

The bridge owns the ROS/Kafka boundary in both directions:

  telemetry path (ROS -> Kafka):
    Subscribes to /<robot_id>/telemetry for every robot in the fleet and
    forwards each message to the fleet.telemetry Kafka topic, keyed by
    robot_id (so each robot's messages stay ordered).

  command path (Kafka -> ROS):
    Consumes fleet.commands from Kafka and publishes each command to
    /<robot_id>/command as a fleet_msgs/RobotCommand. This is how the
    dashboard (or any fleet operator) drives the robots.

Reliability behavior -- the interesting part of this node:
  - Telemetry: a bounded in-memory queue sits between the ROS executor thread
    and a dedicated Kafka sender thread. If Kafka can't keep up, the queue
    fills and the *oldest* data is dropped (telemetry is a stream: fresh data
    beats stale data). Drops are counted and logged, never silent.
  - Sends are async: the sender thread never blocks waiting for a broker
    ack (a synchronous future.get() per message limits throughput to
    ~1 round-trip per message -- measured at ~18/sec vs ~40/sec fleet
    arrival -- and the queue grows without bound). Acks and errors are
    handled in callbacks; kafka-python pipelines and batches internally.
  - Messages that fail serialization go to fleet.telemetry.dlq (dead letter)
    instead of crashing the bridge.
  - Commands: consumed with auto_offset_reset='latest' -- a restarted bridge
    must NEVER replay stale commands (imagine a week-old SHUTDOWN executing
    on boot). Unknown robots and invalid command codes are counted and
    ignored, never forwarded.
  - If Kafka is down, sends fail fast after internal retries, get counted,
    and the bridge keeps serving ROS. It recovers automatically when Kafka
    returns -- verify this with the chaos test in the build guide.
  - Delivery is at-most-once: a message whose retries exhaust is counted
    as failed and dropped. (A requeue-on-error loop would give at-least-once
    at the cost of possible duplicates and redelivery storms during long
    outages -- a deliberate tradeoff for telemetry.)
  - Prometheus metrics are exposed on :<metrics_port>/metrics (default 8001,
    configurable via the metrics_port parameter): forwarded/dropped/failed
    counters, a queue-depth gauge, DLQ and command counters. Every metric
    mirrors one of the plain-int stats counters below, which remain the
    human-readable source in the 30s stats log line.
"""

import json
import os
import queue
import threading
import time

import rclpy
from rclpy.node import Node

from kafka import KafkaConsumer, KafkaProducer

from fleet_msgs.msg import RobotCommand, RobotTelemetry

from prometheus_client import Counter, Gauge, start_http_server

SCHEMA_VERSION = 1

VALID_COMMANDS = (
    RobotCommand.CMD_SET_PUBLISH_RATE,
    RobotCommand.CMD_INJECT_FAULT,
    RobotCommand.CMD_CLEAR_FAULT,
    RobotCommand.CMD_SHUTDOWN,
    RobotCommand.CMD_SET_PARAM,
)


# ---- Prometheus metrics -------------------------------------------------
# One process, one registry: prometheus_client's default. The HTTP server
# started in __init__ serves these on /metrics from its own daemon thread.
# Labels are low-cardinality by design (stage/reason enums, never robot_id
# on high-frequency counters -- per-robot series would explode cardinality).
M_TELEMETRY_FORWARDED = Counter(
    'fleet_bridge_telemetry_forwarded_total',
    'Telemetry messages acked by Kafka')
M_TELEMETRY_DROPPED = Counter(
    'fleet_bridge_telemetry_dropped_total',
    'Telemetry messages dropped because the internal queue was full')
M_TELEMETRY_FAILED = Counter(
    'fleet_bridge_telemetry_failed_total',
    'Telemetry messages lost to Kafka errors', ['stage'])
M_DLQ = Counter(
    'fleet_bridge_dlq_total',
    'Messages routed to the dead-letter topic', ['reason'])
M_QUEUE_DEPTH = Gauge(
    'fleet_bridge_queue_depth',
    'Current depth of the ROS->Kafka telemetry queue')
M_COMMANDS_FORWARDED = Counter(
    'fleet_bridge_commands_forwarded_total',
    'Commands forwarded from Kafka to ROS')
M_COMMANDS_INVALID = Counter(
    'fleet_bridge_commands_invalid_total',
    'Commands rejected before reaching ROS', ['reason'])


def serialize_telemetry(msg: RobotTelemetry) -> bytes:
    """RobotTelemetry -> versioned JSON bytes. Raises on bad input."""
    doc = {
        'schema_version': SCHEMA_VERSION,
        'robot_id': str(msg.robot_id),
        'battery_pct': float(msg.battery_pct),
        'temperature_c': float(msg.temperature_c),
        'x': float(msg.x),
        'y': float(msg.y),
        'status': int(msg.status),
        'ts': float(msg.stamp.sec) + float(msg.stamp.nanosec) / 1e9,
    }
    return json.dumps(doc).encode('utf-8')


class TelemetryBridge(Node):

    def __init__(self):
        super().__init__('telemetry_bridge')

        self.declare_parameter(
            'robot_ids',
            ['robot_1', 'robot_2', 'robot_3', 'robot_4', 'robot_5'])
        # Honors the KAFKA_BOOTSTRAP env var set in the dev container.
        self.declare_parameter(
            'kafka_bootstrap_servers',
            os.environ.get('KAFKA_BOOTSTRAP', 'kafka:29092'))
        self.declare_parameter('telemetry_topic', 'fleet.telemetry')
        self.declare_parameter('dlq_topic', 'fleet.telemetry.dlq')
        self.declare_parameter('commands_topic', 'fleet.commands')
        self.declare_parameter('queue_max_size', 10000)
        self.declare_parameter('metrics_port', 8001)

        self._robot_ids = list(self.get_parameter('robot_ids').value)
        self._telemetry_topic = str(self.get_parameter('telemetry_topic').value)
        self._dlq_topic = str(self.get_parameter('dlq_topic').value)
        self._commands_topic = str(self.get_parameter('commands_topic').value)
        self._kafka_bootstrap = str(
            self.get_parameter('kafka_bootstrap_servers').value)

        self._producer = KafkaProducer(
            bootstrap_servers=self._kafka_bootstrap,
            key_serializer=lambda k: k.encode('utf-8'),
            acks=1,            # leader ack: throughput over durability for telemetry
            retries=5,
            linger_ms=50,      # small batching window
            max_block_ms=5000,
        )

        # ---- telemetry path: ROS -> queue -> Kafka ---------------------
        maxsize = int(self.get_parameter('queue_max_size').value)
        self._queue: 'queue.Queue[tuple[str, bytes]]' = queue.Queue(maxsize=maxsize)
        self._stop = threading.Event()
        self._sender = threading.Thread(
            target=self._sender_loop, daemon=True, name='kafka-sender')
        self._sender.start()

        # One subscription per robot; ROS 2 has no wildcard subscriptions.
        self._subs = []
        for rid in self._robot_ids:
            sub = self.create_subscription(
                RobotTelemetry,
                f'/{rid}/telemetry',
                lambda msg, rid=rid: self._on_telemetry(msg, rid),
                10)
            self._subs.append(sub)

        # ---- command path: Kafka -> ROS -------------------------------
        # One publisher per robot, created upfront. publish() is safe to
        # call from the consumer thread (rclpy publishers are thread-safe).
        self._cmd_pubs = {
            rid: self.create_publisher(RobotCommand, f'/{rid}/command', 10)
            for rid in self._robot_ids
        }
        self._cmd_thread = threading.Thread(
            target=self._command_loop, daemon=True, name='kafka-commands')
        self._cmd_thread.start()

        # Counters are touched from the ROS thread, the sender thread, and
        # kafka-python's callback threads. Plain ints are fine under the GIL
        # for stats; this is not billing data.
        self._forwarded = 0
        self._dropped = 0
        self._failed = 0
        self._dlq = 0
        self._cmd_forwarded = 0
        self._cmd_invalid = 0
        self._last_warn_s = 0.0
        self.create_timer(30.0, self._log_stats)

        # Metrics endpoint. Best-effort by design: a port conflict or bind
        # failure must never take down the data path, so this is wrapped.
        try:
            metrics_port = int(self.get_parameter('metrics_port').value)
            start_http_server(metrics_port, addr='0.0.0.0')
            self.get_logger().info(
                f'prometheus metrics on :{metrics_port}/metrics')
        except Exception as exc:
            self.get_logger().warn(
                f'metrics server failed to start (continuing without): {exc}')

        self.get_logger().info(
            f'bridge online: {len(self._robot_ids)} robots | '
            f'telemetry -> "{self._telemetry_topic}", '
            f'commands <- "{self._commands_topic}" '
            f'(queue_max_size={maxsize})')

    # ------------------------------------------------------------ ROS -> queue

    def _on_telemetry(self, msg: RobotTelemetry, rid: str):
        try:
            payload = serialize_telemetry(msg)
        except Exception as exc:  # malformed -> dead letter, never crash
            self._dlq += 1
            M_DLQ.labels(reason='telemetry_serialize').inc()
            self._send_dlq(rid, repr(msg), str(exc))
            return
        try:
            self._queue.put_nowait((msg.robot_id, payload))
        except queue.Full:
            self._dropped += 1
            M_TELEMETRY_DROPPED.inc()
            self._warn_throttled(
                f'backpressure: queue full, dropping oldest telemetry '
                f'({self._dropped} dropped total)')

    # ------------------------------------------------------------ queue -> Kafka

    def _sender_loop(self):
        """Drain the queue with async sends.

        Never block on a per-message ack here: the producer pipelines and
        batches internally, so acks arrive via callbacks while the loop
        keeps draining. Blocking would serialize the pipeline at
        ~1 broker round-trip per message.
        """
        while not self._stop.is_set():
            try:
                robot_id, payload = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                future = self._producer.send(
                    self._telemetry_topic, key=robot_id, value=payload)
                future.add_callback(self._on_ack)
                future.add_errback(self._on_send_error)
            except Exception as exc:
                # send() itself raised: producer buffer full, closing, ...
                self._failed += 1
                M_TELEMETRY_FAILED.labels(stage='send_error').inc()
                self._warn_throttled(
                    f'kafka send() raised ({self._failed} failed total): {exc}')

    def _on_ack(self, _metadata):
        """Runs on kafka-python's sender thread when the broker acks."""
        self._forwarded += 1
        M_TELEMETRY_FORWARDED.inc()

    def _on_send_error(self, exc):
        """Runs on kafka-python's sender thread after retries exhaust."""
        self._failed += 1
        M_TELEMETRY_FAILED.labels(stage='delivery_error').inc()
        self._warn_throttled(
            f'kafka send failed ({self._failed} failed total): {exc}')

    def _send_dlq(self, robot_id: str, raw: str, error: str):
        try:
            doc = json.dumps({
                'schema_version': SCHEMA_VERSION,
                'robot_id': robot_id,
                'raw': raw,
                'error': error,
                'ts': time.time(),
            }).encode('utf-8')
            self._producer.send(self._dlq_topic, key=robot_id, value=doc)
        except Exception as exc:
            self._warn_throttled(f'dlq send failed: {exc}')

    # ------------------------------------------------------------ Kafka -> ROS

    def _command_loop(self):
        """Consume fleet.commands and publish each to /<robot_id>/command.

        auto_offset_reset='latest' is deliberate and load-bearing: a
        restarted bridge must never replay stale commands. A SHUTDOWN issued
        last week executing on boot would be a very bad day.
        """
        consumer = KafkaConsumer(
            self._commands_topic,
            bootstrap_servers=self._kafka_bootstrap,
            group_id='fleet-bridge-commands',
            auto_offset_reset='latest',
            value_deserializer=lambda b: json.loads(b.decode('utf-8')),
            enable_auto_commit=True,
        )
        self.get_logger().info(
            f'command consumer online: {self._commands_topic}')
        try:
            while not self._stop.is_set():
                batch = consumer.poll(timeout_ms=500)
                for msgs in batch.values():
                    for msg in msgs:
                        self._handle_command(msg.value)
        finally:
            consumer.close()

    def _handle_command(self, doc: dict):
        try:
            robot_id = str(doc['robot_id'])
            command = int(doc['command'])
            value = float(doc.get('value', 0.0))
        except (KeyError, TypeError, ValueError) as exc:
            self._cmd_invalid += 1
            M_COMMANDS_INVALID.labels(reason='malformed').inc()
            M_DLQ.labels(reason='command_malformed').inc()
            self._send_dlq('unknown', json.dumps(doc),
                           f'malformed command: {exc}')
            return
        pub = self._cmd_pubs.get(robot_id)
        if pub is None:
            self._cmd_invalid += 1
            M_COMMANDS_INVALID.labels(reason='unknown_robot').inc()
            self._warn_throttled(
                f'command for unknown robot "{robot_id}" ignored')
            return
        if command not in VALID_COMMANDS:
            self._cmd_invalid += 1
            M_COMMANDS_INVALID.labels(reason='invalid_code').inc()
            self._warn_throttled(f'invalid command code {command} ignored')
            return
        ros_msg = RobotCommand()
        ros_msg.robot_id = robot_id
        ros_msg.command = command
        ros_msg.value = value
        ros_msg.param_name = str(doc.get('param_name', ''))
        pub.publish(ros_msg)
        self._cmd_forwarded += 1
        M_COMMANDS_FORWARDED.inc()
        self.get_logger().info(
            f'command -> {robot_id}: code={command} value={value}')

    # ----------------------------------------------------------------- stats

    def _warn_throttled(self, text: str, interval_s: float = 10.0):
        now = time.monotonic()
        if now - self._last_warn_s >= interval_s:
            self._last_warn_s = now
            self.get_logger().warn(text)

    def _log_stats(self):
        M_QUEUE_DEPTH.set(self._queue.qsize())
        self.get_logger().info(
            f'stats: forwarded={self._forwarded} dropped={self._dropped} '
            f'failed={self._failed} dlq={self._dlq} '
            f'queue_depth={self._queue.qsize()} '
            f'cmd_forwarded={self._cmd_forwarded} '
            f'cmd_invalid={self._cmd_invalid}')

    # -------------------------------------------------------------- shutdown

    def destroy_node(self):
        self.get_logger().info(
            f'shutting down: forwarded={self._forwarded} dropped={self._dropped} '
            f'failed={self._failed} dlq={self._dlq} '
            f'cmd_forwarded={self._cmd_forwarded} '
            f'cmd_invalid={self._cmd_invalid}')
        self._stop.set()
        self._sender.join(timeout=5.0)
        self._cmd_thread.join(timeout=5.0)
        try:
            self._producer.flush(timeout=10)
        finally:
            self._producer.close()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = TelemetryBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
