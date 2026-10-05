import os
import runpy
import subprocess
import sys

"""Helper that lets VS Code's debugger launch a ROS 2 node with one F5.

Usage (from launch.json):  debug_ros.py <installed-script> [node args...]

It sources the ROS + workspace environment in bash, imports the resulting
env vars into this process, then executes the installed console script
in-process via runpy -- so the debugger stays attached and breakpoints
in your node code just work.

Subtlety: PYTHONPATH is only honored at interpreter startup, and this
process is already running by the time we source setup.bash. So we mirror
the sourced PYTHONPATH into sys.path by hand (in order, right behind the
script's own directory -- exactly where startup would have put it).
Without this, the console script's importlib.metadata entry-point lookup
fails with "No package metadata was found".

Requires: pip install debugpy  (inside the dev container, once)

Env overrides (mainly for testing):
  FLEET_ROS_SETUP  default /opt/ros/humble/setup.bash
  FLEET_WS_SETUP   default /root/fleet_ws/install/setup.bash
"""

ROS_SETUP = os.environ.get("FLEET_ROS_SETUP", "/opt/ros/humble/setup.bash")
WS_SETUP = os.environ.get("FLEET_WS_SETUP", "/root/fleet_ws/install/setup.bash")


def _load_ros_env():
    out = subprocess.run(
        ["bash", "-c", f"source {ROS_SETUP} && source {WS_SETUP} && env -0"],
        capture_output=True,
        check=True,
    ).stdout
    for entry in out.split(b"\0"):
        if b"=" in entry:
            k, v = entry.split(b"=", 1)
            os.environ[k.decode()] = v.decode()
    # See module docstring: reproduce interpreter-startup PYTHONPATH handling.
    for p in reversed(os.environ.get("PYTHONPATH", "").split(os.pathsep)):
        if p and p not in sys.path:
            sys.path.insert(1, p)


def main():
    if len(sys.argv) < 2:
        print("usage: debug_ros.py <installed-script> [node args...]", file=sys.stderr)
        sys.exit(2)
    script, node_args = sys.argv[1], sys.argv[2:]
    _load_ros_env()
    sys.argv = [script] + node_args
    runpy.run_path(script, run_name="__main__")


if __name__ == "__main__":
    main()
