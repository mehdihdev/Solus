+++
title = "REP 103 and REP 105: SI units, right-handed frames, and the base_link/odom/map hierarchy"
kind = "principle"
audience = "fundamentals"
applicability = []
derivation = "solus_original"
confidence = 0.9
confidence_basis = "standard_derived"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:software/ros_conventions/tf-tree-hygiene", "corpus:software/ros_conventions/topics-services-actions-and-qos"]
corpus_version = "0.1.0"
revised_in = "0.1.0"

[provenance]
source_class = "solus_authored"
source_title = "Solus engineering corpus"
source_publisher = "Solus"
source_license = "solus-proprietary"
accessed_at = 2026-09-06
checked_against = [
  { title = "REP 103: Standard Units of Measure and Coordinate Conventions", author = "Tully Foote, Mike Purvis (ROS Enhancement Proposals)", identifier = "REP 103", url = "https://www.ros.org/reps/rep-0103.html" },
  { title = "REP 105: Coordinate Frames for Mobile Platforms", author = "Wim Meeussen (ROS Enhancement Proposals)", identifier = "REP 105", url = "https://www.ros.org/reps/rep-0105.html" },
]
+++

ROS makes cross-tool integration possible by fixing conventions that every node is assumed to follow. Two REPs carry most of the load.

REP 103 (standard units and coordinate conventions). Units are base SI without prefixes: metres, kilograms, seconds, radians, and the derived units built from them (m/s, rad/s, N, N·m, A, V, Pa, Hz; temperature in degrees Celsius). No millimetres, no degrees, no grams on the wire; convert at the driver boundary. All coordinate frames are right-handed. For a body-fixed frame on a robot or vehicle (`base_link`), x points forward, y points left, z points up. Camera optical frames are the deliberate exception: z points forward out of the lens, x right, y down, and the frame name carries an `_optical` suffix. For short-range outdoor work the geographic convention is ENU: x east, y north, z up. Rotation follows the same handedness, so a positive yaw is a counter-clockwise turn seen from above. Orientation on the wire is a unit quaternion in (x, y, z, w) order; where Euler angles are used they are fixed-axis roll, pitch, yaw about x, y, z.

REP 105 (coordinate frames for mobile platforms) names a standard frame chain: `earth` → `map` → `odom` → `base_link`. `base_link` is rigidly attached to the robot. `odom` is a world-fixed frame in which the robot's pose is continuous and smooth but drifts without bound; it comes from wheel odometry, visual odometry, or an IMU. `map` is world-fixed and does not drift, but its estimate of the robot may jump when a localiser corrects itself. Consequences: local control and obstacle avoidance consume poses in `odom`; global planning consumes poses in `map`; and the node that localises publishes the `map` → `odom` correction, never `map` → `base_link` directly, so the frame graph stays a tree.

What goes wrong when teams skip this: a CAD export in millimetres becomes a URDF a thousand times too large; an IMU driver reporting degrees per second makes the state estimator diverge; a camera mounted with the body convention instead of the optical convention yields depth points that point at the sky; and a planner fed `odom` poses walks into walls after a loop closure. Solus checkers flag unit and axis mismatches where a source declares them; where a source does not, verify the driver's frame and units against these two REPs before trusting it.
