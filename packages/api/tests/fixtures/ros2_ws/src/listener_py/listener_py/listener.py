# mypy: ignore-errors
"""Fixture data (SOLUSDEV-321 P6): a ROS 2 node's source, read with ast and never imported."""

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class Listener(Node):
    def __init__(self):
        super().__init__("listener")
        self.subscription = self.create_subscription(String, "chatter", self.on_message, 10)

    def on_message(self, message):
        self.get_logger().info(message.data)


def main(args=None):
    rclpy.init(args=args)
    rclpy.spin(Listener())
    rclpy.shutdown()
