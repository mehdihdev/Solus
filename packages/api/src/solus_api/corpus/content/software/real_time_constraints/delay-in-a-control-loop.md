+++
title = "delay() in a control loop is a bug, not a timing mechanism"
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
related = ["corpus:software/real_time_constraints/hard-vs-soft-real-time-and-jitter", "corpus:software/embedded_patterns/superloop-vs-rtos"]
corpus_version = "0.1.0"
revised_in = "0.1.0"

[provenance]
source_class = "solus_authored"
source_title = "Solus engineering corpus"
source_publisher = "Solus"
source_license = "solus-proprietary"
accessed_at = 2026-09-06
checked_against = [
  { title = "Arduino Language Reference: delay(), millis(), micros()", author = "Arduino", identifier = "Arduino language reference", url = "https://www.arduino.cc/" },
  { title = "FreeRTOS API reference: vTaskDelayUntil() / xTaskDelayUntil()", author = "Amazon Web Services / FreeRTOS", identifier = "FreeRTOS kernel docs", url = "https://www.freertos.org/" },
  { title = "Zephyr Project documentation: kernel timing, timers, and k_sleep with absolute timeouts", author = "Zephyr Project", identifier = "Zephyr docs", url = "https://docs.zephyrproject.org/" },
]
+++

The pattern looks harmless:

```
loop() {
  read_sensors();
  compute_control();
  write_outputs();
  delay(10);   // "100 Hz"
}
```

It is not 100 Hz. The period is 10 ms plus however long the three calls took, and that varies with sensor response time, serial traffic, and code path, so the loop rate wanders and every gain you tuned was tuned against a moving dt. Worse, during those 10 ms the core does nothing: it cannot service a serial command, notice an e-stop input, or react to a sensor that became ready early. On Arduino, `delay()` is a busy-wait; only interrupts run underneath it.

The fix is to schedule to absolute time rather than to relative waits:

```
next = millis();
loop() {
  now = millis();
  if ((int32_t)(now - next) >= 0) {   // signed difference survives wrap
    next += 10;
    control_step(now);
  }
  serial_poll();                      // runs every pass, never starved
}
```

The step runs when its deadline arrives, other work fills the gaps, and if one step runs long the schedule catches up instead of drifting permanently. With an RTOS the same idea is `xTaskDelayUntil()` in FreeRTOS, or a `k_timer` / an absolute-timeout `k_sleep` in Zephyr, rather than a plain delay after the work. Better still, drive the control step from a hardware timer interrupt that sets a flag (or gives a semaphore) and do the computation in the loop or task: the sample instant is then fixed by hardware, and compute time adds only latency, not jitter.

Also compute dt from measured timestamps rather than assuming the nominal period. If the measured dt swings by more than a few percent, fix the scheduling before touching the gains.
