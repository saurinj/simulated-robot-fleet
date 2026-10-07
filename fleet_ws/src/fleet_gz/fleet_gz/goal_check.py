#!/usr/bin/env python3
"""GoalCheck: pure observer/examiner for the goal navigation.

Subscribes to /odom and /cmd_vel. Publishes NOTHING.
Watches the brain (goal_robot_node) drive, waits for /cmd_vel to
go to zero, then asserts:
  - Final odom dist is < 0.5.
Exits 0 on PASS, 1 on FAIL. For CI consumption.

Run after the bringup and goal_robot_node are up:
  ros2 run fleet_gz goal_check --ros-args -p use_sim_time:=True
"""
import math

import rclpy
from rclpy.node import Node
from nav_msgs.msg import Odometry
from geometry_msgs.msg import Twist


TIMEOUT_SIM_S = 40.0
STOPPED_CMD_THRESH = 0.01   # |cmd_vel| below this counts as stopped
STOPPED_CONFIRM_S = 2.0     # must hold for this long (sim seconds)


class GoalCheck(Node):
    def __init__(self):
        super().__init__('goal_check')
        self.latest_x = None
        self.latest_y = None
        self.latest_cmd = None
        self.t0 = None
        self.done = False
        self.saw_driving = False
        self.stopped_since = None

        self.declare_parameter('goal_x', 5.0)
        self.declare_parameter('goal_y', 0.0)
        
        self.create_subscription(Odometry, '/odom', self.on_odom, 10)
        self.create_subscription(Twist, '/cmd_vel', self.on_cmd, 10)
        self.create_timer(0.1, self.tick)
        self.get_logger().info('GoalCheck: observing (publishes nothing). '
                               'Waiting for first /clock tick...')

    def on_odom(self, msg: Odometry):
        self.latest_x = msg.pose.pose.position.x
        self.latest_y = msg.pose.pose.position.y

    def on_cmd(self, msg: Twist):
        self.latest_cmd = msg.linear.x

    def tick(self):
        if self.done:
            return
        now = self.get_clock().now()
        if self.t0 is None:
            if now.nanoseconds == 0:
                return  # no /clock yet
            self.t0 = now
            self.get_logger().info(
                'GoalCheck: clock live. Waiting for the brain to drive...')
            return
        t = (now - self.t0).nanoseconds / 1e9

        if self.latest_cmd is None or self.latest_x is None:
            if t > TIMEOUT_SIM_S:
                self.finish(False, 'timed out waiting for /odom or /cmd_vel')
            return

        # Phase 1: wait until the brain is actually driving.
        if not self.saw_driving:
            if abs(self.latest_cmd) > 0.1:
                self.saw_driving = True
                self.get_logger().info('GoalCheck: brain is driving. Watching for stop...')
            elif t > TIMEOUT_SIM_S:
                self.finish(False, 'timed out: brain never started driving')
            return

        # Phase 2: wait for a sustained stop command.
        if abs(self.latest_cmd) < STOPPED_CMD_THRESH:
            if self.stopped_since is None:
                self.stopped_since = t
            elif t - self.stopped_since >= STOPPED_CONFIRM_S:
                self.evaluate()
                return
        else:
            self.stopped_since = None  # still moving; reset

        if t > TIMEOUT_SIM_S:
            self.finish(False, 'timed out: brain never stopped')

    def evaluate(self):
        """The brain stopped. Assert it stopped in the right place for the
        right reason."""

        goal_x = self.get_parameter('goal_x').value
        goal_y = self.get_parameter('goal_y').value
        dist = math.hypot(self.latest_x - goal_x, self.latest_y - goal_y)

        ok = dist < 0.5

        detail = (f'final dist = {dist:.2f}')
        if ok:
            self.finish(True, f'stopped correctly. {detail}')
        else:
            self.finish(False, f'did not stop correctly. {detail}')

    def finish(self, ok: bool, detail: str):
        if self.done:
            return
        self.done = True
        # NOTE: publishes nothing — pure observer.
        msg = f'{"PASS" if ok else "FAIL"}: {detail}'
        self.get_logger().info(msg)
        raise SystemExit(0 if ok else 1)


def main():
    rclpy.init()
    node = GoalCheck()
    try:
        rclpy.spin(node)
    except SystemExit as e:
        raise
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
