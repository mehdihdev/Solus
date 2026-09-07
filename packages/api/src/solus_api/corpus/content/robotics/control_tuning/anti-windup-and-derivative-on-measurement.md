+++
title = "Integral windup and derivative kick: two PID defects that only appear on the real robot"
kind = "pitfall"
audience = "reference"
applicability = []
derivation = "solus_original"
confidence = 0.9
confidence_basis = "consensus"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = [
  "corpus:robotics/control_tuning/what-each-pid-term-does",
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
  { title = "control_toolbox PID documentation (integral clamp parameters)", author = "ros2_control maintainers", url = "https://control.ros.org/" },
  { title = "ODrive documentation, controller and anti-cogging / velocity integrator settings", author = "ODrive Robotics", url = "https://docs.odriverobotics.com/" },
]
+++

Both defects come from the difference between the textbook PID, which assumes an actuator with infinite authority and a smooth setpoint, and a real one that saturates and receives step commands.

Integral windup. When the commanded effort exceeds what the actuator can deliver, the actuator sits at its limit while the error stays large, and the integrator keeps accumulating error it cannot act on. When the measurement finally approaches the setpoint, the integrator holds a large stored command and drives the system well past the target; the loop then needs a long period of opposite error to unwind. It looks like a loop that behaves on small moves and overshoots wildly on large ones, or a joint that continues to push after hitting a mechanical stop. The fixes, in rising order of sophistication: clamp the integrator to a bound (ROS's control_toolbox exposes this as an integral clamp), stop integrating while the output is saturated (conditional integration), or feed the difference between the requested and the achieved output back into the integrator so it settles at the saturation value (back-calculation). Also reset the integrator when the controller is enabled or the setpoint jumps deliberately.

Derivative kick. If the derivative term acts on the error, a step change in setpoint produces an instantaneous spike in de/dt, so the command slams to its limit for one sample. On a motor this is a current spike and an audible click; on a gearbox it is wear. The standard remedy is to take the derivative of the measurement instead of the error: the measurement is continuous even when the setpoint is not, and for a constant setpoint the two are identical up to sign. Nearly every production PID does this; when a controller exposes both options, the measurement form is the one to choose for position loops driven by planners that emit steps.

What to check when a loop misbehaves in only some situations: whether the actuator is saturating during the bad case (log the commanded and the achieved effort together), whether the integrator is bounded, and whether the derivative is on error or on measurement.
