+++
title = "Tuning a PID loop by hand"
kind = "procedure"
audience = "fundamentals"
applicability = []
derivation = "solus_original"
confidence = 0.8
confidence_basis = "rule_of_thumb"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = [
  "corpus:robotics/control_tuning/what-each-pid-term-does",
  "corpus:robotics/control_tuning/anti-windup-and-derivative-on-measurement",
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
  { title = "ODrive documentation, control loop tuning procedure", author = "ODrive Robotics", url = "https://docs.odriverobotics.com/" },
  { title = "ros2_control and control_toolbox documentation, PID controller", author = "ros2_control maintainers", url = "https://control.ros.org/" },
  { title = "DYNAMIXEL e-Manual, position PID gain settings", author = "ROBOTIS", url = "https://emanual.robotis.com/" },
]
+++

This is the procedure for a single loop on a real actuator when you have no model and a plot of setpoint against measurement. It assumes the sample rate is already adequate and the sign of the loop is right (a positive command moves the measurement positive); check both first, because no gain fixes a wrong sign.

1. Set Ki and Kd to zero. Apply a small step in setpoint, small enough that the actuator does not saturate, and look at the response.
2. Raise Kp until the response just begins to oscillate steadily after the step, then back it off to somewhere around half that value. You now have a loop that responds briskly with some overshoot and a steady-state offset if gravity or friction is present.
3. Add Kd in small increments until the overshoot is trimmed and the oscillation dies within one or two swings. If the command becomes jittery, the measurement is too noisy for that much derivative: filter the derivative term or reduce Kd rather than accepting the noise.
4. Add Ki, starting very small, until the steady offset disappears in an acceptable time. If overshoot grows again, reduce Ki or accept a slower settle; if the loop overshoots grossly after a large move, integral windup is the cause and the integrator needs a clamp.
5. Repeat the step in both directions and at the extremes of the working range. Gravity load, friction, and inertia all change with pose, so gains tuned at one pose can oscillate at another. Tune for the worst pose and accept a slower response elsewhere.
6. Test a disturbance (push the joint, add a payload) separately from a setpoint step. Some loops track steps well and reject disturbances badly.

Limits of the procedure: it produces a safe, moderately quick loop, not an optimal one; it does not apply to systems with significant delay, which oscillate at low gain and need a different approach; and on a cascaded controller it must be done inner loop first with the outer loops open. Vendor tools for smart servos and motor drivers usually expose the same three gains under their own scaling, so record the units alongside the values.
