+++
title = "URDF conventions that break a model: joint frames, axis frames, radians, and fixed-axis rpy"
kind = "pitfall"
audience = "reference"
applicability = []
derivation = "solus_original"
confidence = 0.9
confidence_basis = "standard_derived"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = [
  "corpus:robotics/kinematics_basics/frames-and-transforms",
]
further_reading = []
corpus_version = "0.1.0"
revised_in = "0.1.0"

[provenance]
source_class = "solus_authored"
source_title = "Solus engineering corpus"
source_publisher = "Solus"
source_license = "solus-proprietary"
accessed_at = 2026-09-06
checked_against = [
  { title = "URDF XML specification: joint and link elements", author = "Open Robotics", url = "https://wiki.ros.org/urdf" },
  { title = "REP 103: Standard Units of Measure and Coordinate Conventions", author = "Open Robotics", identifier = "REP 103", url = "https://www.ros.org/reps/rep-0103.html" },
  { title = "ROS 2 documentation, URDF tutorials", author = "Open Robotics", url = "https://docs.ros.org/" },
]
+++

A URDF describes a tree of links connected by joints, and its conventions differ from the Denavit–Hartenberg (DH) tables in most textbooks. DH places frames so that four parameters per joint suffice and the frame for joint i often sits on the axis of joint i+1; URDF places one frame per link at an arbitrary location you choose, and the joint carries a full six-parameter origin. A DH table cannot be typed into a URDF field by field, and a CAD export will not match a DH model without a deliberate mapping.

The rules that are most often violated:

- A joint's `origin` is the transform from the parent link frame to the child link frame at the joint's zero position. The joint frame and the child link frame are the same frame.
- A joint's `axis` is expressed in that child/joint frame, not in the parent frame and not in the world. Rotate the joint origin and the axis rotates with it.
- All angles are radians (REP 103). A limit written as `upper="90"` is about fourteen revolutions, not a right angle, and most tools will not warn.
- `rpy` is roll about x, then pitch about y, then yaw about z, each about the fixed parent axes. A CAD tool exporting intrinsic angles or a different order will produce a model whose links are visibly twisted only in some poses.
- Units are metres and kilograms. An export in millimetres makes a robot a thousand times too large; masses left at a default of 1 kg make dynamics and simulation wrong even though visualisation looks fine.
- Every link except the root needs exactly one parent joint; a link with no joint is silently disconnected and transform queries to it fail.

What to check when a model looks right at zero pose but wrong when moved: the joint axis frame (parent vs child), the rpy order, and the joint limit units. A model that is right in every pose but behaves wrongly in simulation usually has correct kinematics and wrong `inertial` blocks.
