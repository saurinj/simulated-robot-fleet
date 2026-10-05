# Telemetry snapshot published by each robot (~10 Hz).
# This is the fleet's API contract: every consumer (bridge, dashboard,
# alerting) depends on this shape, so changes here are versioned carefully.

string robot_id          # unique robot identifier, e.g. "robot_1"

float32 battery_pct      # 0-100
float32 temperature_c    # onboard computer temperature

float64 x                # simulated 2D position, meters
float64 y

uint8 status             # one of the STATUS_* constants below
uint8 STATUS_OK=0
uint8 STATUS_DEGRADED=1
uint8 STATUS_FAULT=2
uint8 STATUS_OFFLINE=3

builtin_interfaces/Time stamp
