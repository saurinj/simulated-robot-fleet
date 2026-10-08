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
from rclpy.node import Node
from rclpy.duration import Duration
from sensor_msgs.msg import LaserScan
from nav_msgs.msg import Odometry
from geometry_msgs.msg import Twist, Vector3

from fleet_gz.goal_steer_node import GoalSteerNode

FORWARD_SPEED = 0.25      # m/s
STOP_DIST_M = 0.8         # stop when forward sector < this
PUBLISH_HZ = 10.0
SECTOR_HALF_DEG = 30.0    # forward wedge half-angle
RANGE_MIN = 0.05          # ignore closer than this (sensor noise)
RANGE_MAX = 12.0          # ignore farther than this

class GoalWithObstacleSteerNode(GoalSteerNode):
    def __init__(self):
        super().__init__('goal_with_obstacle_steer_robot_node')
        self.latest_scan = None
        self.avoid_until = None

        self.last_scan_time = None

        self.create_subscription(LaserScan, '/scan', self.on_scan, 10)

    def on_scan(self, msg: LaserScan):
        self.latest_scan = msg
        self.last_scan_time = self.get_clock().now()

    def sector_min(self) -> float:
        """Min valid range in the forward wedge, derived from the scan's
        own angle_min/angle_increment (robust to index-0 convention)."""
        msg = self.latest_scan
        half_rad = math.radians(SECTOR_HALF_DEG)
        valid = []
        for i, r in enumerate(msg.ranges):
            a = msg.angle_min + i * msg.angle_increment
            a = (a + math.pi) % (2 * math.pi) - math.pi  # wrap to [-pi, pi]
            if abs(a) <= half_rad and math.isfinite(r) \
                    and RANGE_MIN < r < RANGE_MAX:
                valid.append(r)
        return min(valid) if valid else float('inf')

    def get_twist(self, fwd_dist, heading_error, dist) -> Twist:
        # obstacle check comes first, rest logic is same as previous version
        now = self.get_clock().now()
        if self.avoid_until is not None and now < self.avoid_until:
            cmd = Twist(linear=Vector3(x=0.0), angular=Vector3(z=0.5))
        elif fwd_dist < STOP_DIST_M:
            # Obstacle! start 2-sec turn
            self.avoid_until = now + Duration(seconds=2.0)
            cmd = Twist(linear=Vector3(x=0.0), angular=Vector3(z=0.5))
        else:
            self.avoid_until = None
            cmd = super().get_twist(heading_error, dist)
        return cmd
    
    def tick(self):
        if self.latest_ori is None or self.latest_pos is None or self.latest_scan is None:
            return

        now = self.get_clock().now()
        # Sensor-dropout failsafe - return after 10 messages (10 messages come in 1 sec)
        if (now - self.last_scan_time > Duration(seconds=1.0)):
            self.get_logger().info('SCAN STALE')
            # publish 0 twist otherwise robot will continue driving forward
            self.cmd_pub.publish(Twist())
            return
        # Sensor-dropout failsafe - return after 10 messages (10 messages come in 1 sec)
        if (now - self.last_odom_time > Duration(seconds=1.0)):
            self.get_logger().info('ODOM STALE')
            # publish 0 twist otherwise robot will continue driving forward
            self.cmd_pub.publish(Twist()) 
            return

        p = self.latest_pos
        goal_x = self.get_parameter('goal_x').value
        goal_y = self.get_parameter('goal_y').value

        dx = goal_x - p.x
        dy = goal_y - p.y
        
        dist = self.calculate_dist(dx, dy)
        heading_error = self.calculate_heading_error(dx, dy)

        # Check forward lidar
        fwd_dist = self.sector_min()
        self.get_logger().info(
            f'fwd_dist={fwd_dist:.2f} pos=({p.x:.2f},{p.y:.2f})',
            throttle_duration_sec=1.0)

        # move robot
        cmd = self.get_twist(fwd_dist, heading_error, dist)
        self.cmd_pub.publish(cmd)

def main():
    rclpy.init()
    node = GoalWithObstacleSteerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
