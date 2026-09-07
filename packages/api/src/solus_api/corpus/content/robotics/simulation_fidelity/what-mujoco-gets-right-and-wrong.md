+++
title = "What MuJoCo models well and badly, and why the URDF mass matters"
kind = "principle"
audience = "fundamentals"
applicability = []
derivation = "solus_original"
confidence = 0.85
confidence_basis = "consensus"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = [
  "corpus:robotics/dynamics_basics/reflected-inertia-and-gravity",
  "corpus:robotics/kinematics_basics/urdf-conventions-that-break-models",
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
  { title = "MuJoCo documentation: Overview, Modeling, and Computation chapters (soft contacts, solref/solimp, timestep, inertia)", author = "Google DeepMind", url = "https://mujoco.readthedocs.io/" },
  { title = "URDF XML specification, link inertial element", author = "Open Robotics", url = "https://wiki.ros.org/urdf" },
]
+++

MuJoCo is a rigid-body simulator built for speed and stable contact. It models articulated chains, joint limits, actuators, and contact between simple geometric primitives very well, and it does so fast enough to run many copies in parallel, which is why it dominates learning-based control. Its contact model is deliberately soft: penetration is allowed and pushed back by a spring-damper-like constraint whose stiffness and how it saturates are set by the solver reference and impedance parameters (solref and solimp) rather than by material properties. That makes contact stable at large time steps, but it means the numbers are tuning knobs, not physics: a real gripper on a real steel part does not have a tunable penetration depth.

What it models badly or not at all: deformation (cables, soft grippers, bending links), fluids and aerodynamics, gear backlash and the torque-speed curve of a real motor unless you model them explicitly, sensor noise and latency unless you add them, and mesh-to-mesh contact, which is approximated through convex hulls so concave shapes gain phantom volume. Friction is a per-geom coefficient with no stick-slip dynamics, so anything that depends on the fine behaviour of friction (a wheel at the edge of traction, an insertion task) will transfer to hardware less well than a free-space motion.

The mass and inertia in your URDF or MJCF are not cosmetic. They set how the simulated links respond to actuator torque and gravity, the natural frequencies of the chain, and how stable the integrator is: very light bodies attached to very heavy ones, or bodies with tiny or non-physical inertias, make the constraint solver struggle at the default time step. MuJoCo will infer inertia from geometry when told to, but a URDF that carries default masses of 1 kg for every link or an inertia tensor copied from a different part produces a robot that is either unstable in simulation or, worse, stable and tuned to the wrong dynamics, so that controller gains carry across to hardware wrongly.

Sim-to-real gaps therefore come from three places in order of frequency: wrong inertial parameters, contact behaviour that was tuned rather than measured, and actuator models that ignore current and thermal limits. Before blaming the simulator, check the masses.
