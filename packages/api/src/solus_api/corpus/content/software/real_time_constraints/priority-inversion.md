+++
title = "Priority inversion: a low-priority task holding a mutex can stall your control loop"
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
related = ["corpus:software/real_time_constraints/hard-vs-soft-real-time-and-jitter", "corpus:software/embedded_patterns/isr-discipline"]
corpus_version = "0.1.0"
revised_in = "0.1.0"

[provenance]
source_class = "solus_authored"
source_title = "Solus engineering corpus"
source_publisher = "Solus"
source_license = "solus-proprietary"
accessed_at = 2026-09-06
checked_against = [
  { title = "FreeRTOS kernel documentation: mutexes, priority inheritance, and binary semaphores", author = "Amazon Web Services / FreeRTOS", identifier = "FreeRTOS kernel docs", url = "https://www.freertos.org/" },
  { title = "Zephyr Project documentation: mutexes (k_mutex) and priority inheritance", author = "Zephyr Project", identifier = "Zephyr docs", url = "https://docs.zephyrproject.org/" },
]
+++

Priority inversion is what happens when the scheduler does exactly what you told it and your high-priority task still misses its deadline. Setup: a high-priority control task and a low-priority logging task both lock a mutex around a shared resource (an I2C bus, a shared buffer). The low task takes the mutex; the high task wakes, tries to take it, and blocks, as it should. Now a medium-priority task (telemetry, display) becomes ready. It outranks the low task, so it runs, and keeps running, while the low task, the only one that can release the mutex, never gets the CPU. The high-priority task is effectively waiting on the medium one, which never touched the resource. That is the inversion, and it can last indefinitely.

Defences, in the order to reach for them:

- Do not share the resource. Give the bus or buffer one owner task and have the others send requests through a queue. No mutex, no inversion.
- If you must share, use a mutex with priority inheritance: while a low task holds a mutex that a higher task is waiting on, the holder is temporarily raised to the waiter's priority so the medium task cannot preempt it. FreeRTOS mutexes (`xSemaphoreCreateMutex`) implement inheritance; its binary semaphores do not, which is why "I used a semaphore as a lock" is a classic cause. Zephyr's `k_mutex` implements it too.
- Keep critical sections short and never do I/O while holding a lock. Inheritance bounds the inversion to the length of the critical section; a 30 ms flash write under a mutex is a 30 ms hole in your 1 ms loop.
- Never take a mutex from an ISR, and never block on one in a task with a hard deadline unless you have measured the worst-case hold time of every other holder.

How to recognise it: the high-priority task's period is normally clean but occasionally stretches by an amount that matches some unrelated mid-priority activity (a display refresh, a telemetry burst). Trace the mutex: who held it, and who was running while the holder waited. RTOS trace tools and the invariant "the highest-priority ready task should be the one running" make it visible.
