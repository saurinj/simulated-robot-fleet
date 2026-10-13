#!/usr/bin/env python3
"""RobotNode: goal-seeking driver that is an extension to previous version goal_steer_node. 
It reaches goal (the 'brain' under test) by steering even when there is obstacle.

Follows "Roomba" algorithm - when blocked, turn left. When clear, resume navigation.

Subscribes to /odom, publishes /cmd_vel at 10 Hz. Drives forward at
0.25 m/s until goal_x, goal_y are achieved, then stops by
publishing zero velocity continuously.

This node contains the AUTONOMY BEHAVIOR. It is the code under test.
The test harness (goal_check) observes from the outside and asserts.
RobotNode knows nothing about tests, pass bands, or timeouts.
"""

import math

import rclpy
from nav_msgs.msg import Odometry
from geometry_msgs.msg import Twist, Point

from fleet_gz.goal_with_obstacle_steer_node import GoalWithObstacleSteerNode

PEER_TOO_CLOSE_DIST = 1.0      # meter

SPAWN = {
    'robot1': (0.0, 0.0), 
    'robot2': (0.0, 3.0), 
    'robot3': (3.0, 0.0)
}

class FleetAwareRobotNode(GoalWithObstacleSteerNode):
    def __init__(self, node_name='fleet_aware_robot_node'):
        super().__init__(node_name)

        self.peer_pos = {}
        self.my_id = self.get_namespace().strip('/')
        self.declare_parameter('robot_ids', ['robot1', 'robot2', 'robot3'])
        self.peer_robot_ids = list(self.get_parameter('robot_ids').value)
        self.peer_robot_ids.remove(self.my_id)
        
        for rid in self.peer_robot_ids:
            self.peer_pos[rid] = None
            self.create_subscription(
                Odometry,
                f'/{rid}/odom',
                lambda msg, rid=rid: self._on_odom(msg, rid),
                10)
  
    def _on_odom(self, msg, rid):
        self.peer_pos[rid] = msg.pose.pose.position

    def get_twist(self, fwd_dist, heading_error, dist) -> Twist:
        # if too close to a peer then return 0 twist
        if self.peer_too_close():
            return Twist()
        
        return super().get_twist(fwd_dist, heading_error, dist)
    
    def peer_too_close(self) -> bool:
        ix, iy = self.map_pos(self.latest_pos, self.my_id)

        for rid in self.peer_robot_ids:
            if self.peer_pos[rid] is not None:
                jx, jy = self.map_peer_pos(rid)
                dist = math.hypot(jx - ix, jy - iy)
                if dist < PEER_TOO_CLOSE_DIST and dist > 1e-3 and self.is_higher_number_robot(rid):
                    self.get_logger().info(f'FleetAwareRobotNode: peer too close between {rid} and {self.my_id} -> dist:{dist}')
                    return True
        return False

    def map_peer_pos(self, rid):
        p = self.peer_pos[rid]
        return self.map_pos(p, rid)
    
    @staticmethod
    def map_pos(pos: Point, rid):
        sx, sy = SPAWN[rid]
        return (pos.x + sx, pos.y + sy)

    # make sure only higher number robot stops, so that both robots don't stop for entirity
    def is_higher_number_robot(self, rid) -> bool:
        return int(rid[-1]) < int(self.my_id[-1])

def main():
    rclpy.init()
    node = FleetAwareRobotNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
