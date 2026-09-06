+++
title = "Interrupt handlers: grab the data, set a flag, get out"
kind = "rule_of_thumb"
audience = "reference"
applicability = []
derivation = "solus_original"
confidence = 0.85
confidence_basis = "consensus"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:software/embedded_patterns/superloop-vs-rtos", "corpus:software/real_time_constraints/priority-inversion"]
corpus_version = "0.1.0"
revised_in = "0.1.0"

[provenance]
source_class = "solus_authored"
source_title = "Solus engineering corpus"
source_publisher = "Solus"
source_license = "solus-proprietary"
accessed_at = 2026-09-06
checked_against = [
  { title = "FreeRTOS API reference: interrupt-safe (FromISR) functions and interrupt nesting", author = "Amazon Web Services / FreeRTOS", identifier = "FreeRTOS kernel docs", url = "https://www.freertos.org/" },
  { title = "Arduino Language Reference: attachInterrupt(), volatile, millis(), delay()", author = "Arduino", identifier = "Arduino language reference", url = "https://www.arduino.cc/" },
  { title = "Zephyr Project documentation: interrupts and ISR-safe APIs", author = "Zephyr Project", identifier = "Zephyr docs", url = "https://docs.zephyrproject.org/" },
]
+++

An interrupt service routine runs with the main code (or the RTOS scheduler) frozen, so every microsecond spent in it is stolen from everything else, including other interrupts on cores without nesting. The discipline:

- Do the minimum. Read the register that raised the interrupt, copy the byte or sample into a buffer, set a flag or push to a queue, clear the interrupt source, return. Process in the main loop or a task.
- No dynamic allocation (`malloc`, `new`, string formatting), no printing, no floating point on cores without a hardware FPU, no blocking calls of any kind. On FreeRTOS use only the API functions with the `FromISR` suffix; the others may try to block or yield and will corrupt scheduler state.
- Anything an ISR writes and the main code reads must be declared `volatile`, otherwise the compiler may legitimately keep the old value in a register and the main loop never sees the change. `volatile` is not atomicity: on an 8-bit AVR a 16-bit or 32-bit variable is written in several instructions, and the main code can read a half-old, half-new value. Use a type the core writes in one instruction, disable interrupts briefly around the read, or use the platform's atomic types.
- A ring buffer with one producer (the ISR) and one consumer (main) is lock-free if head and tail are each written by only one side and each is a single-word write.
- Clear or re-arm the interrupt flag the way the reference manual says. A flag that is not cleared re-enters the ISR immediately and starves the main code; a flag cleared before the data is read can drop a sample on peripherals that clear on read.

Rule of thumb for length: an ISR that takes more than a few microseconds on a 100 MHz-class core, or more than a few tens of microseconds on an 8-bit AVR, is doing work that belongs in the main loop. If you find yourself wanting `delay()` inside a handler, the design is wrong. The Arduino reference itself warns that `delay()` does not work and `millis()` stops advancing inside an ISR, because both depend on a timer interrupt that cannot run while another handler is executing.
