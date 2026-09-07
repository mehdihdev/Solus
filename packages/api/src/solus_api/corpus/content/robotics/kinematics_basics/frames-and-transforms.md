+++
title = "Frames and transforms: a pose is always relative to another frame"
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
related = [
  "corpus:robotics/kinematics_basics/forward-inverse-and-the-jacobian",
  "corpus:robotics/kinematics_basics/urdf-conventions-that-break-models",
]
further_reading = [
  { title = "Introduction to Robotics: Mechanics and Control", author = "Craig", identifier = "ISBN 978-0133489798" },
]
corpus_version = "0.1.0"
revised_in = "0.1.0"

[provenance]
source_class = "solus_authored"
source_title = "Solus engineering corpus"
source_publisher = "Solus"
source_license = "solus-proprietary"
accessed_at = 2026-09-06
checked_against = [
  { title = "REP 103: Standard Units of Measure and Coordinate Conventions", author = "Open Robotics", identifier = "REP 103", url = "https://www.ros.org/reps/rep-0103.html" },
  { title = "REP 105: Coordinate Frames for Mobile Platforms", author = "Open Robotics", identifier = "REP 105", url = "https://www.ros.org/reps/rep-0105.html" },
  { title = "ROS 2 documentation, tf2 concepts and tutorials", author = "Open Robotics", url = "https://docs.ros.org/" },
]
+++

A coordinate frame is an origin plus three perpendicular axes. Every position, orientation, velocity, or force in a robot is expressed in some frame, and a number without its frame is meaningless: the same point is (0.3, 0, 0.2) in the base frame and (0, 0, 0) in the gripper frame.

A transform describes one frame relative to another. It carries a translation (where the child origin sits, measured in the parent's axes) and a rotation (how the child axes are turned relative to the parent's). Writing it as T_parent_child, the rule that makes everything else work is composition: T_a_c = T_a_b · T_b_c. A chain of links is just a product of transforms, one per joint, and a point known in the last frame is moved into the first by multiplying through the chain. Inverting a transform flips the relationship: T_b_a is the inverse of T_a_b.

Rotations are the part that bites newcomers. Three Euler angles are compact but their meaning depends on the order and on whether each rotation is about the fixed parent axes or the already-rotated child axes; rotation matrices and quaternions are unambiguous, which is why tooling stores them that way and treats angles as an input convenience. Conventions on the ROS side are written down in REP 103: right-handed frames, SI units, angles in radians, and for a body frame x forward, y left, z up. REP 105 names the standard mobile-robot frames: base_link fixed to the body, odom which is continuous but drifts, and map which is globally consistent but may jump when a localiser corrects itself.

For an engineer arriving from electronics, the useful mental model is a netlist of frames: each frame has exactly one parent, transforms are the wires, and a query for "where is the camera relative to the wheel" is a path through the tree. If two frames have no path between them, no tool can answer the question, and that is the most common first bug in a new robot description.
