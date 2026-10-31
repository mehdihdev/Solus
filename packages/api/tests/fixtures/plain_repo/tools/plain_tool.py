# mypy: ignore-errors
"""Fixture data (SOLUSDEV-321 P6): a plain repository's module, with no ROS package and no
policy. A call named like a node API is only text here: no package.xml makes it ROS."""


def plain_report(publisher, rows):
    publisher.create_publisher("not-ros", "/not_a_topic", 10)
    return [row for row in rows if row]
