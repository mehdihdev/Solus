+++
title = "Servo, stepper, BLDC, and DC gearmotor: which family fits which joint"
kind = "rule_of_thumb"
audience = "reference"
applicability = []
derivation = "solus_original"
confidence = 0.8
confidence_basis = "consensus"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = [
  "corpus:robotics/actuator_selection/size-from-the-load-not-the-catalogue",
  "corpus:robotics/actuator_selection/stall-torque-is-not-a-rating",
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
  { title = "DYNAMIXEL e-Manual, integrated servo specifications and control modes", author = "ROBOTIS", url = "https://emanual.robotis.com/" },
  { title = "ODrive documentation, motor guide and control modes", author = "ODrive Robotics", url = "https://docs.odriverobotics.com/" },
  { title = "Pololu stepper motor and gearmotor product documentation", author = "Pololu", url = "https://www.pololu.com/" },
  { title = "maxon product catalogue, brushed and brushless DC motors", author = "maxon", url = "https://www.maxongroup.com/" },
]
+++

The families differ less in physics than in what is already integrated and what you must add yourself. The table is a starting point, not a specification.

| Family | Position feedback | Torque behaviour | Typical fit | Watch for |
| --- | --- | --- | --- | --- |
| Integrated servo (hobby or smart, e.g. DYNAMIXEL-class) | Built in, closed loop on position | Quoted at stall, often in kgf·cm | Arms, grippers, small legged robots, anywhere a bus-addressed joint saves wiring | Continuous torque well below the stall figure; limited speed range; gear train backlash |
| Stepper (open loop) | None unless you add an encoder | Highest at standstill, falls as speed rises | Gantries, low-speed precise positioning, anything that can tolerate a lost step being undetected | Missed steps under overload are silent; runs hot at full current even when still |
| BLDC with a field-oriented driver | Encoder or resolver you fit and align | Smooth, high power density, controllable down to zero speed | Direct-drive or low-ratio joints, wheels, high-performance arms | You own the driver, encoder alignment, and tuning; cost of the driver often exceeds the motor |
| Brushed DC gearmotor | Add an encoder on the motor or output | Simple: torque is proportional to current | Wheels, low-cost joints, prototypes | Brush life; gearbox backlash; efficiency lost through several stages |

Rules that hold across the families: torque scales with current and heat scales with current squared, so the continuous rating is a thermal number regardless of family; adding a gearbox raises torque and lowers speed by the ratio, minus the gearbox's losses; and any open-loop actuator (steppers, unencoded DC) cannot report that it failed to reach the commanded position. When a checker sees a stepper driving a joint that also carries a gravity load with no encoder, that is the pattern to warn about.
