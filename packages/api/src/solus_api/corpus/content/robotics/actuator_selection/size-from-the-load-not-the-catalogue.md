+++
title = "Size an actuator from the load's torque, speed, and duty cycle, not from the catalogue"
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
  "corpus:robotics/actuator_selection/stall-torque-is-not-a-rating",
  "corpus:robotics/actuator_selection/motor-family-trade-offs",
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
  { title = "maxon product catalogue and motor selection guidance", author = "maxon", url = "https://www.maxongroup.com/" },
  { title = "DYNAMIXEL e-Manual, actuator performance specifications", author = "ROBOTIS", url = "https://emanual.robotis.com/" },
  { title = "ODrive documentation, motor guide", author = "ODrive Robotics", url = "https://docs.odriverobotics.com/" },
]
+++

An actuator is chosen by working backwards from what the joint must do, not forwards from what a catalogue offers. Three numbers describe the job, and each comes from the mechanism, not from the motor.

Torque at the joint has three parts: the static load (gravity acting on the links and payload through their lever arms, at the worst-case pose), the acceleration load (the moment of inertia of everything downstream of the joint times the peak angular acceleration the motion profile demands), and friction in bearings, seals, and the gearbox. Add them at the pose and instant where they peak together. That sum is the peak torque the actuator must deliver at the output shaft.

Speed is the peak angular velocity of the joint in the motion profile, at the output. A gearbox trades speed for torque: output torque rises with the ratio (less the gearbox's losses) and output speed falls by the same ratio, so the ratio is chosen so the motor's comfortable speed range lands on the joint's required speed range.

Duty cycle decides which torque rating you compare against. A joint that holds a pose against gravity for minutes needs its holding torque to sit under the actuator's continuous rating, because continuous torque is a thermal limit: heating in the windings grows with the square of current, and current is proportional to torque. A joint that only bursts briefly can use the actuator's peak rating for the burst, provided the average heating over the cycle stays inside the continuous rating.

Only after these three numbers exist does the catalogue matter. A common failure is to pick a motor because its headline torque looks larger than the load, and to discover that the headline figure was stall torque, that the gearbox ate a fraction of it, and that holding the arm level exceeds the continuous rating and cooks the winding.
