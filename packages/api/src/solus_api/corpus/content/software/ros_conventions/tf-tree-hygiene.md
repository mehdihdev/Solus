+++
title = "tf tree hygiene: one parent per frame, one publisher per transform, honest timestamps"
kind = "pitfall"
audience = "reference"
applicability = []
derivation = "solus_original"
confidence = 0.85
confidence_basis = "consensus"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:software/ros_conventions/rep-103-units-and-frames", "corpus:software/ros_conventions/topics-services-actions-and-qos"]
corpus_version = "0.1.0"
revised_in = "0.1.0"

[provenance]
source_class = "solus_authored"
source_title = "Solus engineering corpus"
source_publisher = "Solus"
source_license = "solus-proprietary"
accessed_at = 2026-09-06
checked_against = [
  { title = "ROS 2 documentation: tf2 tutorials (Introducing tf2, static broadcaster, view_frames, tf2_echo)", author = "Open Robotics / ROS 2", identifier = "ROS 2 docs, Tutorials, tf2", url = "https://docs.ros.org/" },
  { title = "REP 105: Coordinate Frames for Mobile Platforms", author = "Wim Meeussen (ROS Enhancement Proposals)", identifier = "REP 105", url = "https://www.ros.org/reps/rep-0105.html" },
]
+++

tf2 stores transforms as a tree: every frame has exactly one parent, and a lookup between any two frames walks up to their common ancestor. Most tf problems are violations of that shape, or of time.

- One parent per frame, one publisher per edge. If two nodes both publish `odom` → `base_link` (a wheel-odometry driver and a sensor-fusion node, say), the tree flickers between them and every lookup jitters. Decide which node owns each edge and turn publication off in the other; drivers usually expose a parameter for exactly this. The same applies to `map` → `odom`: the localiser owns it and nothing else may publish it.
- Static transforms go on `/tf_static`, published once with transient-local durability, not re-broadcast at 50 Hz on `/tf`. Sensor mounts, camera optical frames, and everything the URDF defines belong there through `robot_state_publisher`; a hand-published static edge should match the URDF, not duplicate it with different numbers.
- A transform's timestamp is the time it was valid, taken from the same clock as the data it will transform. Stamping "now" on a transform derived from a 40 ms old sensor reading makes the point cloud lag the robot. Mixing a node on simulation time with one on wall time produces lookups thousands of seconds apart and constant extrapolation errors.
- A lookup at time t needs transforms bracketing t in the buffer. Asking for the latest available transform (time zero) avoids extrapolation errors at the cost of using whatever is newest; asking for an exact stamp on a slow (say 1 Hz) edge fails until the next message arrives. Tune buffer duration and publication rates together.
- Frame names are spelled as REP 105 spells them (`base_link`, `odom`, `map`) and carry no leading slash in ROS 2.

Diagnostics: `ros2 run tf2_tools view_frames` draws the tree and, for each edge, shows who broadcasts it, at what rate, and how recent the newest transform is. Two broadcasters on one edge, a frame with two parents, or a rate of zero on an edge you expected are all visible there. `ros2 run tf2_ros tf2_echo source target` prints the actual transform and its age. Fix the tree before tuning anything downstream; a localiser cannot converge against a flickering tf.
