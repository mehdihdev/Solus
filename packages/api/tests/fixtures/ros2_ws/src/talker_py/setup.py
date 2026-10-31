# mypy: ignore-errors
"""Fixture data (SOLUSDEV-321 P6): a ROS package's build file, read with ast and never run."""

from setuptools import find_packages, setup

package_name = "talker_py"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/launch", ["launch/talker.launch.py"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    entry_points={"console_scripts": ["talker = talker_py.talker:main"]},
)
