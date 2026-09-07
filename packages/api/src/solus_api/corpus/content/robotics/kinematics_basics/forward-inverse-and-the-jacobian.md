+++
title = "Forward and inverse kinematics, the Jacobian, and singularities, at the level of intuition"
kind = "principle"
audience = "fundamentals"
applicability = []
derivation = "solus_original"
confidence = 0.9
confidence_basis = "consensus"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = [
  "corpus:robotics/kinematics_basics/frames-and-transforms",
]
further_reading = [
  { title = "Modern Robotics: Mechanics, Planning, and Control", author = "Lynch, Park", identifier = "ISBN 978-1107156302" },
  { title = "Robotics: Modelling, Planning and Control", author = "Siciliano, Sciavicco, Villani, Oriolo", identifier = "ISBN 978-1846286414" },
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
  { title = "MoveIt documentation, kinematics and inverse kinematics solvers", author = "PickNik Robotics", url = "https://moveit.picknik.ai/" },
  { title = "MuJoCo documentation, Computation chapter (kinematics and Jacobians)", author = "Google DeepMind", url = "https://mujoco.readthedocs.io/" },
  { title = "ROS 2 documentation, URDF and tf2 tutorials", author = "Open Robotics", url = "https://docs.ros.org/" },
]
+++

Forward kinematics answers: given every joint angle, where is the tool? It is a product of transforms down the chain and always has exactly one answer. Inverse kinematics answers the harder question: given where I want the tool, what joint angles put it there? It may have several answers (elbow up or elbow down), infinitely many (a 7-joint arm reaching a 6-degree-of-freedom pose has a spare degree of freedom), or none (the target is outside the workspace). Solvers are therefore either closed-form for a specific geometry or iterative, and iterative solvers need a starting guess and can fail to converge.

The Jacobian is the bridge between the two. It is the matrix that says, for a small change in each joint, how the tool moves and rotates: joint velocities in, tool velocity out. Its transpose does the same for forces in the other direction, which is why the same matrix shows up in force control. An iterative IK solver is essentially "use the Jacobian to guess which joint motion reduces the pose error, step, repeat".

A singularity is a pose where the Jacobian loses rank: some direction of tool motion has become unreachable, however the joints move. The intuitive picture is a fully extended arm, which cannot move its hand any further outward, or two rotation axes lining up so they produce the same motion and one degree of freedom has effectively vanished. Near a singularity the mathematics does not fail cleanly; instead, a small tool velocity in the lost direction demands enormous joint velocities, so the controller commands motions the actuators cannot follow, and the arm jerks or the solver returns garbage. Planners avoid these regions or damp the solution.

Workspace is the set of poses the tool can reach. Reachable workspace is where the tool can be placed at all; dexterous workspace is where it can also be oriented freely. A target that is reachable only at the very edge is a target at a singularity, so a working margin inside the reachable envelope is a design requirement, not a nicety.
