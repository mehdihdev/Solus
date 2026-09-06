+++
title = "Superloop or RTOS: decide by how many unrelated deadlines the firmware must meet"
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
related = ["corpus:software/embedded_patterns/isr-discipline", "corpus:software/real_time_constraints/delay-in-a-control-loop"]
corpus_version = "0.1.0"
revised_in = "0.1.0"

[provenance]
source_class = "solus_authored"
source_title = "Solus engineering corpus"
source_publisher = "Solus"
source_license = "solus-proprietary"
accessed_at = 2026-09-06
checked_against = [
  { title = "FreeRTOS kernel documentation: tasks, scheduling, and inter-task communication", author = "Amazon Web Services / FreeRTOS", identifier = "FreeRTOS kernel docs", url = "https://www.freertos.org/" },
  { title = "Zephyr Project documentation: kernel services (threads, scheduling, synchronisation)", author = "Zephyr Project", identifier = "Zephyr docs", url = "https://docs.zephyrproject.org/" },
]
+++

A superloop is the simplest firmware structure: initialise the hardware, then run one `while (1)` that polls inputs, advances any state machines, and writes outputs, forever. Nothing preempts anything except interrupts. It is easy to reason about, has no scheduler overhead, and on a small MCU (an AVR, an RP2040 reading one sensor) it is usually the right answer.

It stops being the right answer when the loop has to meet several unrelated deadlines at once. A control step that must run every 1 ms, a serial parser that must drain its buffer before it overflows, and a display refresh that takes 30 ms cannot share one loop without the slow job stretching the fast job's period. You end up hand-slicing the display update into fragments so the control step still fits: a scheduler written by hand, badly.

An RTOS (FreeRTOS, Zephyr) gives you that scheduler properly: tasks with priorities, a tick, and blocking primitives (queues, semaphores, event flags) so a task sleeps until its data arrives instead of polling. The highest-priority task that is ready always runs, so the 1 ms control task preempts the display task mid-draw and the fast path's timing no longer depends on the slow path's worst case.

The cost is real: every task needs its own stack (RAM on a small part is the usual limit), shared data now needs protection (a mutex or a queue, never a bare global), and bugs become time-dependent and harder to reproduce. Rules that hold either way:

- Never busy-wait inside the loop or a task when a blocking call or a state machine could yield instead.
- Keep hardware access in non-blocking drivers that start an operation and report completion later (flag, callback, queue message).
- Measure the worst-case execution time of the slowest job. If it exceeds the period of the fastest job, the superloop has already failed and the RTOS decision is made for you.

Practical threshold: one or two periodic jobs with similar periods, superloop. Three or more jobs whose periods differ by more than about ten to one, or any job that must wait on an external event without stalling the rest, RTOS.
