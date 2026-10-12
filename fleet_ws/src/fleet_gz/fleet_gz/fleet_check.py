#!/usr/bin/env python3
"""FleetCheck: an examiner that examines fleet of robots.

Subscribes to /odom. Publishes NOTHING.
Watches the brain (goal_with_obstacle_steer_node) drive, waits for /odom to
go to zero, then asserts:
  -  True, if all three reach their assigned goals and not collided with any other robot
Exits 0 on PASS, 1 on FAIL. For CI consumption.

Run after the bringup and goal_with_obstacle_steer_node are up:
  ros2 run fleet_gz goal_with_obstacle_steer_node --ros-args -p use_sim_time:=True
"""
import math

import rclpy
from rclpy.node import Node
from nav_msgs.msg import Odometry

TIMEOUT_SIM_S = 90.0

GOALS = {
    'robot1': (4.0, 4.0),
    'robot2': (-4.0, 4.0),
    'robot3': (4.0, -4.0),
}

SPAWN = {
    'robot1': (0.0, 0.0), 
    'robot2': (0.0, 3.0), 
    'robot3': (3.0, 0.0)
}

class FleetCheck(Node):
    def __init__(self):
        super().__init__('fleet_check')
        self.latest_pos = {}
        self.t0 = {}
        self.done = {}
        self.arrived = {}

        self.declare_parameter('robot_ids', ['robot1', 'robot2', 'robot3'])
        self._robot_ids = list(self.get_parameter('robot_ids').value)

        for rid in self._robot_ids:
            self.latest_pos[rid] = None
            self.t0[rid] = None
            self.done[rid] = None
            self.arrived[rid] = None
            self.create_subscription(
                Odometry,
                f'/{rid}/odom',
                lambda msg, rid=rid: self._on_odom(msg, rid),
                10)

        self.create_timer(0.1, self.tick_all)
        
        self.get_logger().info('FleetCheck: observing (publishes nothing). '
                               'Waiting for first /clock tick...')


    def _on_odom(self, msg, rid):
        self.latest_pos[rid] = msg.pose.pose.position

    def tick_all(self):
        for rid in self._robot_ids:
            self.tick(rid)

    def tick(self, rid):
        if self.done[rid]:
            return

        now = self.get_clock().now()
        if self.t0[rid] is None:
            if now.nanoseconds == 0:
                return  # no /clock yet
            self.t0[rid] = now
            self.get_logger().info(
                f'FleetCheck: clock live. Waiting for the {rid} brain to drive...')
            return
        t = (now - self.t0[rid]).nanoseconds / 1e9

        if self.latest_pos[rid] is None:
            if t > TIMEOUT_SIM_S:
                self.finish(False, f'timed out waiting for {rid}/odom', rid)
            return

        # Phase2: evaulate
        if self.latest_pos[rid] is not None:
            self.evaluate(rid)

        if t > TIMEOUT_SIM_S:
            self.finish(False, f'{rid} timed out waiting for arrival', rid)

    def evaluate(self, rid):
        # check if reached the destination
        if self.collided(rid):
            self.finish(False, f'{rid} Collided.', rid)
            return
        elif self.reached_goal(rid):
            self.arrived[rid] = True
            if self.all_arrived():
                self.finish(True, f'{rid} stopped correctly.', rid)

    def reached_goal(self, rid):
        mx, my = self.map_pos(rid)
        dist = math.hypot(mx - GOALS[rid][0], my - GOALS[rid][1])

        if dist < 0.3:
            self.get_logger().info(f'{rid} dist = {dist:.2f}')
            return True
        else:
            return False

    def collided(self, input_rid):
        if (self.latest_pos[input_rid] is None):
            return False
        ix, iy = self.map_pos(input_rid)

        for rid in self._robot_ids:
            if rid != input_rid and self.latest_pos[rid] is not None:
                jx, jy = self.map_pos(rid)
                dist = math.hypot(jx - ix, jy - iy)
                if dist < 0.3 and dist > 1e-3:
                    self.get_logger().info(f'FleetCheck: collision between {rid} and {input_rid} -> dist:{dist}')
                    return True
        return False

    def map_pos(self, rid):
        p = self.latest_pos[rid]
        sx, sy = SPAWN[rid]
        return (p.x + sx, p.y + sy)

    def finish(self, ok: bool, detail: str, rid):
        if self.done[rid]:
            return
        self.done[rid] = True
        # NOTE: publishes nothing — pure observer.
        msg = f'{"PASS" if ok else "FAIL"}: {detail}'
        self.get_logger().info(msg)

        if not ok:
            raise SystemExit(1)
        if self.all_arrived():
            raise SystemExit(0)

    def all_arrived(self) -> bool:
        arrived = True
        for rid in self._robot_ids:
            arrived = arrived and self.arrived[rid];
        return arrived

def main():
    rclpy.init()
    node = FleetCheck()
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
