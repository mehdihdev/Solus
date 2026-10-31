# mypy: ignore-errors
"""Not part of the ROS package: it makes the fixture's two `setup.py` files distinct modules, so
the type-check gate does not stop on a duplicate module named `setup`."""
