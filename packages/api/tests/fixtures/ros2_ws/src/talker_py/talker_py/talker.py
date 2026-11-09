# mypy: ignore-errors
"""Fixture data (SOLUSDEV-321 P6): a ROS 2 node's source, read with ast and never imported."""

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class Talker(Node):
    def __init__(self):
        super().__init__("talker")
        self.publisher = self.create_publisher(String, "chatter", 10)
        self.timer = self.create_timer(0.5, self.tick)

    def tick(self):
        message = String()
        message.data = "hello"
        self.publisher.publish(message)


def main(args=None):
    rclpy.init(args=args)
    rclpy.spin(Talker())
    rclpy.shutdown()
