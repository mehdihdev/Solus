+++
title = "What each PID term does to the response"
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
  "corpus:robotics/control_tuning/tuning-a-loop-by-hand",
  "corpus:robotics/control_tuning/anti-windup-and-derivative-on-measurement",
  "corpus:robotics/control_tuning/sample-rate-and-cascaded-loops",
]
further_reading = [
  { title = "Feedback Systems: An Introduction for Scientists and Engineers", author = "Åström, Murray", identifier = "ISBN 978-0691193984" },
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
  { title = "ros2_control and control_toolbox documentation, PID controller parameters", author = "ros2_control maintainers", url = "https://control.ros.org/" },
  { title = "ODrive documentation, control loop tuning", author = "ODrive Robotics", url = "https://docs.odriverobotics.com/" },
]
+++

A PID controller computes a command from the error e = setpoint − measurement. In the common parallel form:

```
u(t) = Kp · e(t) + Ki · ∫ e(τ) dτ + Kd · de/dt
```

Each term corrects a different failing of the others, and hearing what each one does to a step response is most of what tuning by hand requires.

Proportional, Kp, pushes in proportion to how far you are from the target. Larger Kp reaches the target faster and resists disturbances harder, but the response overshoots more and eventually oscillates, because by the time the error is zero the system is still moving. On its own, P also leaves a steady error whenever a constant effort is needed to hold position (gravity on an arm, friction in a drive): at the exact setpoint the error is zero, so the command is zero, so the arm sags until the error is big enough to hold it.

Integral, Ki, accumulates that leftover error and keeps pushing until it is gone, so it removes the steady offset. The cost is that it acts on the past, adding lag: it slows the response, increases overshoot, and if the actuator saturates it keeps accumulating (windup) and then overshoots badly once the actuator comes back into range.

Derivative, Kd, pushes against the rate of change of the error, so it acts like damping: it lets you raise Kp without oscillating and it trims overshoot. Its cost is noise amplification, since differentiating a noisy measurement produces a large, jittery command, and it is nearly useless at low sample rates where the difference between consecutive samples is dominated by quantisation.

For an electrical engineer, the equivalents are exact: P is a resistor's proportional relationship, I is the capacitor that keeps charging while a voltage error persists, D is the inductor-like term that opposes change. A loop with too little damping rings like an underdamped RLC circuit, and for the same reason.
