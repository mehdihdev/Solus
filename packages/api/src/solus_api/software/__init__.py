"""SOLUSDEV-321 P6 — software depth: pure readers of what a repository's software states.

`ros_reader` reads a ROS workspace's nodes and topics from its package texts; `policy_reader` reads
a learned policy's and its controller's interface widths. Both are pure (texts in, facts out), make
no model call (`tests/test_model_call_sites.py`), read by STRUCTURE and name no framework, vendor or
connector (both hygiene ratchets sweep this package from its first file). Nothing a reader is
handed is ever executed, imported or loaded: Python is read with `ast.parse`, XML through the
manifest parser's DTD-refusing root, YAML with `safe_load` behind a byte cap and an alias refusal.
"""
