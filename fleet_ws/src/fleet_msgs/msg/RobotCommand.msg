# Command sent TO a robot (e.g. from the fleet dashboard / OTA service).
# Companion to RobotTelemetry: telemetry flows robot -> fleet,
# commands flow fleet -> robot.

string robot_id

uint8 command            # one of the CMD_* constants below
uint8 CMD_SET_PUBLISH_RATE=0
uint8 CMD_INJECT_FAULT=1
uint8 CMD_CLEAR_FAULT=2
uint8 CMD_SHUTDOWN=3
uint8 CMD_SET_PARAM=4       # OTA config push: set a tunable ROS parameter

float32 value            # command argument, e.g. new publish rate in Hz
string param_name        # OTA config: which parameter to set (only with CMD_SET_PARAM)
