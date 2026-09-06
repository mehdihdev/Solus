+++
title = "Reflected inertia, gravity torque, and why the arm sags"
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
  "corpus:robotics/actuator_selection/size-from-the-load-not-the-catalogue",
  "corpus:robotics/control_tuning/what-each-pid-term-does",
]
further_reading = [
  { title = "Modern Robotics: Mechanics, Planning, and Control", author = "Lynch, Park", identifier = "ISBN 978-1107156302" },
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
  { title = "maxon product catalogue and selection guidance (gear ratio, load inertia matching)", author = "maxon", url = "https://www.maxongroup.com/" },
  { title = "MuJoCo documentation, Modeling chapter (inertial properties of bodies)", author = "Google DeepMind", url = "https://mujoco.readthedocs.io/" },
  { title = "URDF XML specification, link inertial element", author = "Open Robotics", url = "https://wiki.ros.org/urdf" },
]
+++

A joint's motor never feels the load directly; it feels the load through the gearbox, and the gearbox scales inertia by the square of its ratio. A load inertia J_load behind a ratio N looks to the motor like:

```
J_reflected = J_load / N²
```

Doubling the ratio quarters the inertia the motor has to accelerate, which is why high-ratio gearboxes make a small motor feel like it is driving a light arm. The same relation runs the other way: the motor's own rotor inertia, seen from the joint, is multiplied by N². At high ratios the rotor dominates what the joint feels, so the arm is hard to push by hand, impacts are transmitted stiffly into the gear teeth, and backdrivability is lost. This is the central trade of actuator design: high ratio for torque density and small motors, low ratio for compliance and fast, safe interaction with the world.

Gravity acts as a torque at each joint equal to the weight of everything downstream times the horizontal distance from the joint axis to that mass's centre. It is largest with the arm horizontal and zero with the arm vertical, and it changes continuously with pose. A position controller with only a proportional term holds against it by letting the joint fall until the error is large enough to produce the holding torque; that is why the arm sags, and why the sag is worst at full horizontal reach. An integral term removes the sag slowly; gravity compensation removes it instantly by computing the gravity torque from the model (the masses and centres of mass in the URDF) and adding it to the command as a feedforward, leaving the feedback loop to handle only errors. That is also why wrong or default masses in the robot description produce an arm that sags or lifts in the real world even though the simulator looks fine.

Payload rating on a datasheet is the mass the arm can carry at its rated speed and reach while staying inside every joint's continuous torque and the gearbox's limits. Carrying it at a longer reach, or at higher acceleration, exceeds those limits even though the mass has not changed; the rating is a torque budget expressed as a mass, not a mass limit.
