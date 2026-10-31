# mypy: ignore-errors
"""Fixture data (SOLUSDEV-321 P6): a Python launch file, read with ast and never executed."""

from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription(
        [
            Node(
                package="talker_py",
                executable="talker",
                name="talker",
                namespace="robot",
            ),
        ]
    )
