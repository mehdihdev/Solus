+++
title = "Real time means bounded latency, not fast: hard versus soft deadlines and jitter budgets"
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
related = ["corpus:software/real_time_constraints/delay-in-a-control-loop", "corpus:software/real_time_constraints/priority-inversion", "corpus:software/embedded_patterns/superloop-vs-rtos"]
corpus_version = "0.1.0"
revised_in = "0.1.0"

[provenance]
source_class = "solus_authored"
source_title = "Solus engineering corpus"
source_publisher = "Solus"
source_license = "solus-proprietary"
accessed_at = 2026-09-06
checked_against = [
  { title = "ROS 2 design article: Introduction to Real-time Systems", author = "Open Robotics / ROS 2 design", identifier = "design.ros2.org real-time background", url = "https://design.ros2.org/" },
  { title = "FreeRTOS kernel documentation: scheduling, tick, and task priorities", author = "Amazon Web Services / FreeRTOS", identifier = "FreeRTOS kernel docs", url = "https://www.freertos.org/" },
  { title = "Zephyr Project documentation: scheduling and timing", author = "Zephyr Project", identifier = "Zephyr docs", url = "https://docs.zephyrproject.org/" },
]
+++

"Real time" does not mean fast. It means every instance of a job finishes before a known deadline, with a bound you can state. A 1 kHz motor current loop on a 48 MHz microcontroller is real time; a 500 Hz camera pipeline on a 2 GHz desktop that occasionally stalls for 80 ms is not.

Hard real time: missing a deadline is a failure of the system. The current loop of a motor driver, a brake or e-stop response, a sample that must be taken at a fixed phase. These jobs are designed around worst-case execution time, not the average.

Soft real time: a late result still has value, just less. Path planning, logging, visualisation, most ROS topic processing. These are designed around throughput and a tolerable lateness distribution.

Two numbers describe a periodic job's timing. Latency is the delay between the event (timer tick, sensor ready) and the moment your code responds. Jitter is the cycle-to-cycle variation in that delay. For a controller, jitter is usually the worse enemy: a constant 200 µs latency is a phase lag you can model and tune around; 0 to 200 µs of random jitter is unmodelled noise injected into every derivative term and integration step. A working rule of thumb for typical PID loops is to keep jitter under a few percent of the loop period and to treat anything over about 10 % as a bug to fix before tuning.

Where jitter comes from, in the order to look: blocking calls in the loop (delay, printf, a serial write that waits for buffer space); long or nested interrupt handlers; on a general-purpose OS, the scheduler and other processes; and last, and smallest on an MCU, cache and memory effects. On a Linux computer such as a Jetson or a Raspberry Pi, a plain user-space loop cannot deliver hard real time. That is why robots put current and position loops on a microcontroller or a motor controller with its own MCU, and let the Linux host send setpoints at a lower, soft-real-time rate.

Budgeting: write down the period, the worst-case execution time you have measured (not estimated), the largest interrupt or blocking delay, and the jitter you can tolerate. If the sum of worst cases exceeds the period, no amount of optimising the average case helps.
