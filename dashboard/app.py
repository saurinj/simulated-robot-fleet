#!/usr/bin/env python3
"""Fleet dashboard backend.

The "cloud side" of the architecture: consumes fleet.telemetry from Kafka,
keeps the latest state per robot, evaluates alert rules (edge-triggered, so
no alert spam), publishes alerts and recovery notices to fleet.alerts,
and serves a REST API plus a static single-page frontend.

This service never touches ROS. Run it on the host (or any machine with Kafka
access) -- conceptually it lives in the cloud, not in the robot network.

Run:
    pip install -r requirements.txt
    KAFKA_BOOTSTRAP=localhost:9092 uvicorn app:app --port 8000
Then open http://localhost:8000
"""

import json
import os
import threading
import time
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from kafka import KafkaConsumer, KafkaProducer

BASE_DIR = Path(__file__).parent

KAFKA_BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP", "localhost:9092")
TELEMETRY_TOPIC = os.environ.get("TELEMETRY_TOPIC", "fleet.telemetry")
ALERTS_TOPIC = os.environ.get("ALERTS_TOPIC", "fleet.alerts")
COMMANDS_TOPIC = os.environ.get("COMMANDS_TOPIC", "fleet.commands")

# Mirrors the CMD_* constants in fleet_msgs/msg/RobotCommand.msg.
# The dashboard speaks names; the bridge translates to codes on the ROS side.
COMMANDS = {
    "set_publish_rate": 0,
    "inject_fault": 1,
    "clear_fault": 2,
    "shutdown": 3,
    "set_param": 4,  # OTA config push; requires param_name
}

STALE_AFTER_S = 5.0
MAX_ALERTS = 200

STATUS_LABELS = {0: "OK", 1: "DEGRADED", 2: "FAULT", 3: "OFFLINE"}

RECOVERY_MESSAGES = {
    "fault": "FAULT cleared — robot OK",
    "degraded": "no longer DEGRADED",
    "stale": "telemetry resumed",
    "low_battery_warn": "battery back above warning threshold",
    "low_battery_crit": "battery back above critical threshold",
    "overtemp_warn": "temperature back below warning threshold",
    "overtemp_crit": "temperature back below critical threshold",
}


@dataclass
class RobotState:
    robot_id: str
    telemetry: dict = field(default_factory=dict)
    last_seen: float = 0.0
    active: set = field(default_factory=set)  # alert keys currently firing


states: dict[str, RobotState] = {}
alerts: deque[dict] = deque(maxlen=MAX_ALERTS)
lock = threading.Lock()
stop = threading.Event()
producer: KafkaProducer | None = None
kafka_ok = threading.Event()


# ------------------------------------------------------------- alert rules

def evaluate_rules(tele: dict) -> list[tuple[str, str, str]]:
    """Return [(key, severity, message)] for rules firing on this message."""
    fired = []
    batt = float(tele.get("battery_pct", 100.0))
    temp = float(tele.get("temperature_c", 25.0))
    status = int(tele.get("status", 0))

    if batt < 15:
        fired.append(("low_battery_crit", "critical",
                      f"battery critically low: {batt:.1f}%"))
    elif batt < 30:
        fired.append(("low_battery_warn", "warning",
                      f"battery low: {batt:.1f}%"))
    if temp > 65:
        fired.append(("overtemp_crit", "critical",
                      f"overheating: {temp:.1f}C"))
    elif temp > 55:
        fired.append(("overtemp_warn", "warning",
                      f"temperature high: {temp:.1f}C"))
    if status == 2:
        fired.append(("fault", "critical", "robot reports FAULT"))
    elif status == 1:
        fired.append(("degraded", "warning", "robot reports DEGRADED"))
    return fired


def _fire_locked(robot_id: str, key: str, severity: str, message: str):
    """Edge-triggered: only fires on transition into the condition."""
    st = states[robot_id]
    if key in st.active:
        return
    st.active.add(key)
    alert = {"ts": time.time(), "robot_id": robot_id,
             "severity": severity, "rule": key, "message": message}
    alerts.appendleft(alert)
    if producer is not None:
        try:
            producer.send(ALERTS_TOPIC, alert)
        except Exception:
            pass  # alerting must never break ingestion
    print(f"ALERT [{severity}] {robot_id}: {message}", flush=True)


def _recover_locked(robot_id: str, key: str):
    """Edge-triggered recovery: feed + fleet.alerts entry when a firing
    condition clears, so the incident has a visible end."""
    st = states[robot_id]
    if key not in st.active:
        return
    st.active.discard(key)
    entry = {"ts": time.time(), "robot_id": robot_id, "severity": "recovered",
             "rule": key,
             "message": RECOVERY_MESSAGES.get(key, f"{key} cleared")}
    alerts.appendleft(entry)
    if producer is not None:
        try:
            producer.send(ALERTS_TOPIC, entry)
        except Exception:
            pass  # alerting must never break ingestion
    print(f"RECOVERED {robot_id}: {entry['message']}", flush=True)


def handle_telemetry(tele: dict):
    rid = str(tele.get("robot_id", "unknown"))
    with lock:
        st = states.setdefault(rid, RobotState(robot_id=rid))
        st.telemetry = tele
        st.last_seen = time.time()
        fired = {k: (sev, msg) for k, sev, msg in evaluate_rules(tele)}
        for key in [k for k in st.active if not k.startswith("stale")]:
            if key not in fired:
                _recover_locked(rid, key)
        for key, (sev, msg) in fired.items():
            _fire_locked(rid, key, sev, msg)


def sweeper_loop():
    """Background thread: edge-triggered STALE alerts based on last_seen."""
    while not stop.is_set():
        now = time.time()
        with lock:
            for rid, st in states.items():
                if st.last_seen == 0:
                    continue
                age = now - st.last_seen
                if age > STALE_AFTER_S and "stale" not in st.active:
                    _fire_locked(rid, "stale", "warning",
                                 f"no telemetry for {age:.0f}s (stale/offline)")
                elif age <= STALE_AFTER_S and "stale" in st.active:
                    _recover_locked(rid, "stale")
        stop.wait(2.0)


def consume_loop():
    consumer = KafkaConsumer(
        TELEMETRY_TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP,
        group_id="fleet-dashboard",
        auto_offset_reset="latest",  # live view, not history replay
        value_deserializer=lambda b: json.loads(b.decode("utf-8")),
        enable_auto_commit=True,
    )
    kafka_ok.set()
    try:
        while not stop.is_set():
            batch = consumer.poll(timeout_ms=500)
            for msgs in batch.values():
                for msg in msgs:
                    try:
                        handle_telemetry(msg.value)
                    except Exception as exc:
                        print(f"warn: bad telemetry message: {exc}", flush=True)
    finally:
        kafka_ok.clear()
        consumer.close()


# ------------------------------------------------------------------- app

@asynccontextmanager
async def lifespan(app: FastAPI):
    global producer
    producer = KafkaProducer(
        bootstrap_servers=KAFKA_BOOTSTRAP,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        key_serializer=lambda k: str(k).encode("utf-8"),
        max_block_ms=5000,
    )
    threads = [
        threading.Thread(target=consume_loop, daemon=True, name="kafka-consumer"),
        threading.Thread(target=sweeper_loop, daemon=True, name="stale-sweeper"),
    ]
    for t in threads:
        t.start()
    print(f"dashboard: consuming {TELEMETRY_TOPIC} from {KAFKA_BOOTSTRAP}",
          flush=True)
    yield
    stop.set()
    for t in threads:
        t.join(timeout=5.0)
    if producer is not None:
        producer.close()


app = FastAPI(title="Fleet Ops Dashboard")
app.router.lifespan_context = lifespan
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/api/robots")
def api_robots():
    now = time.time()
    out = []
    with lock:
        for rid in sorted(states):
            st = states[rid]
            tele = st.telemetry
            age = now - st.last_seen if st.last_seen else None
            stale = age is not None and age > STALE_AFTER_S
            out.append({
                "robot_id": rid,
                "status": tele.get("status"),
                "status_label": "STALE" if stale else STATUS_LABELS.get(
                    tele.get("status"), "?"),
                "battery_pct": tele.get("battery_pct"),
                "temperature_c": tele.get("temperature_c"),
                "x": tele.get("x"),
                "y": tele.get("y"),
                "last_seen_age_s": round(age, 1) if age is not None else None,
                "active_alerts": sorted(st.active),
            })
    return {"robots": out, "ts": now}


@app.get("/api/alerts")
def api_alerts(limit: int = 50):
    with lock:
        return {"alerts": list(alerts)[: max(1, min(limit, MAX_ALERTS))]}


@app.get("/api/health")
def api_health():
    with lock:
        n = len(states)
    return {"status": "ok", "kafka_connected": kafka_ok.is_set(),
            "robots_seen": n, "ts": time.time()}


class CommandRequest(BaseModel):
    command: str  # one of COMMANDS, e.g. "inject_fault"
    value: float = 0.0  # argument, e.g. new publish rate in Hz
    param_name: str = ""  # OTA config: which parameter to set (set_param only)


@app.post("/api/robots/{robot_id}/command")
def api_command(robot_id: str, req: CommandRequest):
    """Fleet operator command: dashboard -> fleet.commands -> bridge -> robot."""
    if req.command not in COMMANDS:
        raise HTTPException(
            400, f"unknown command {req.command!r}; known: {sorted(COMMANDS)}")
    if req.command == "set_param" and not req.param_name:
        raise HTTPException(400, "set_param requires param_name")
    with lock:
        known = robot_id in states
    if not known:
        raise HTTPException(404, f"unknown robot: {robot_id}")
    doc = {"schema_version": 1, "robot_id": robot_id,
           "command": COMMANDS[req.command], "value": float(req.value),
           "param_name": req.param_name,
           "ts": time.time()}
    if producer is not None:
        producer.send(COMMANDS_TOPIC, key=robot_id, value=doc)
    print(f"COMMAND {robot_id}: {req.command} value={req.value}"
          f" param={req.param_name}", flush=True)
    return {"ok": True, "sent": doc}
