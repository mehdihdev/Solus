+++
title = "Sample rate versus bandwidth, and why position sits over velocity over current"
kind = "rule_of_thumb"
audience = "reference"
applicability = []
derivation = "solus_original"
confidence = 0.75
confidence_basis = "rule_of_thumb"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = [
  "corpus:robotics/control_tuning/what-each-pid-term-does",
  "corpus:robotics/control_tuning/tuning-a-loop-by-hand",
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
  { title = "ODrive documentation, control structure (current, velocity, position loops)", author = "ODrive Robotics", url = "https://docs.odriverobotics.com/" },
  { title = "ros2_control documentation, controller update rates and hardware interfaces", author = "ros2_control maintainers", url = "https://control.ros.org/" },
]
+++

A digital controller only sees the plant at sample instants, and the delay between a measurement and the command it produces eats phase margin. The working rule of thumb is to run the loop at least ten times faster than the closed-loop bandwidth you want; twenty to thirty times is comfortable. Below about ten times, the sampling delay alone forces you to lower gains until the loop is sluggish, and the derivative term stops meaning anything because consecutive samples differ by a few counts of quantisation. The rule has limits: it says nothing about the sensor's own latency (a camera at 30 frames per second caps position-loop bandwidth regardless of how fast the controller runs), and it assumes jitter is small; a loop that runs at 1 kHz on average but occasionally stalls for 20 ms behaves like a much slower loop.

Motor control is almost always cascaded, and the order is not arbitrary. The innermost loop regulates current (hence torque), because the electrical time constant of a winding is the fastest dynamics in the system and current is what actually damages hardware; it typically runs at several kilohertz or more, often in the driver. Around it, a velocity loop commands current to hold a speed, rejecting friction and load disturbances before they become position errors. Outermost, a position loop commands velocity. Each outer loop should be slower than the one inside it by a comfortable factor, commonly a handful of times, so the inner loop looks to the outer loop like an ideal actuator that simply does what it is told.

Cascading pays in three ways: each loop is a simple, low-order plant that tunes by hand; saturation and limits are enforced where they belong (a current limit protects the motor, a velocity limit protects the mechanism); and a fault in one layer is visible in that layer's error rather than smeared across the whole system. The cost is that the loops must be tuned from the inside out, and an outer loop tuned against a badly tuned inner loop inherits its problems.

When a checker sees a position controller commanded from a planner at 50 Hz with a target bandwidth of tens of hertz, or a velocity loop running slower than the position loop that feeds it, those are the configurations worth a warning.
