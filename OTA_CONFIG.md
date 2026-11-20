# OTA config push — design

How a fleet operator changes a robot's configuration at runtime, and why
the robot (not the dashboard or the bridge) has the final say.

## Path

```
dashboard (POST /api/robots/{robot_id}/command)
  -> Kafka topic fleet.commands   (key = robot_id, JSON, schema_version 1)
  -> bridge (command consumer thread)
  -> ROS topic /<robot_id>/command (fleet_msgs/RobotCommand)
  -> robot_node._apply_ota_param()
```

Telemetry flows robot -> fleet; commands flow fleet -> robot. Both go
through Kafka so the dashboard never talks DDS directly.

## Commands

Defined in `fleet_ws/src/fleet_msgs/msg/RobotCommand.msg`:

| Code | Constant | Argument | Effect on the robot |
|---|---|---|---|
| 0 | `CMD_SET_PUBLISH_RATE` | `value` (Hz) | Sets `publish_rate_hz`, clamped to [0.5, 50.0] |
| 1 | `CMD_INJECT_FAULT` | — | Latches `STATUS_FAULT` until cleared |
| 2 | `CMD_CLEAR_FAULT` | — | Clears a commanded fault, back to `STATUS_OK` |
| 3 | `CMD_SHUTDOWN` | — | Robot node exits |
| 4 | `CMD_SET_PARAM` | `param_name`, `value` | OTA config push for one tunable parameter (below) |

## The allowlist lives on the robot

`OTA_PARAMS` in `fleet_ws/src/fleet_bot/fleet_bot/robot_node.py`:

| Parameter | Type | Allowed range |
|---|---|---|
| `publish_rate_hz` | double | 0.5 – 50.0 |
| `fault_probability` | double | 0.0 – 1.0 |
| `recover_probability` | double | 0.0 – 1.0 |

- **Not in the list = rejected.** The robot logs `rejected OTA param ... not tunable` and changes nothing.
- **In the list = clamped, not rejected.** An out-of-range value is pulled to the nearest bound, so a typo can't push a robot into an unsafe setting.
- **`robot_id` is deliberately not tunable.** A robot's identity never changes over the air.
- **Why the robot, not the bridge:** the bridge only checks that the command code is valid. A compromised or buggy publisher could bypass the bridge and talk DDS directly, so the last line of defense has to be on the robot.

## Validation at each hop

| Hop | Checks |
|---|---|
| Dashboard API | Known command name; `set_param` requires `param_name`; robot must have been seen in telemetry (else 404) |
| Bridge | Valid command code and known `robot_id`; anything else is counted in `fleet_bridge_commands_invalid_total{reason}` (`malformed` / `unknown_robot` / `invalid_code`) and never forwarded |
| Robot | Allowlist + clamp (above) |

## Delivery semantics

- **No stale replays.** The bridge's command consumer uses `auto_offset_reset='latest'`. A restarted bridge must never replay old commands — a week-old `SHUTDOWN` executing on boot would be a very bad day.
- **At-most-once.** If the bridge is down when a command is published, that command is not delivered later. For config, the operator re-sends; for a real fleet, desired-state reconciliation (below) would close this gap.
- **Observable.** Forwarded commands are counted in `fleet_bridge_commands_forwarded_total`; every applied change is logged by the robot (`OTA config: <name> -> <value>`).

## Try it

```bash
kubectl port-forward -n fleet svc/dashboard 8000:8000

curl -s -X POST localhost:8000/api/robots/robot_1/command \
  -H 'Content-Type: application/json' \
  -d '{"command": "set_param", "param_name": "publish_rate_hz", "value": 2.0}'

kubectl logs -n fleet deploy/fleet | grep "OTA config"
```

## Not built yet

- Desired-state reconciliation (robot reports its config; the fleet re-sends until it converges)
- Staged rollout of a config change across the fleet (canary robot first, then the rest)
- Signed commands / per-robot authorization
