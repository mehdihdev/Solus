+++
title = "A watchdog fed from a timer interrupt protects nothing"
kind = "pitfall"
audience = "reference"
applicability = []
derivation = "solus_original"
confidence = 0.85
confidence_basis = "consensus"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:software/embedded_patterns/superloop-vs-rtos", "corpus:software/embedded_patterns/isr-discipline"]
corpus_version = "0.1.0"
revised_in = "0.1.0"

[provenance]
source_class = "solus_authored"
source_title = "Solus engineering corpus"
source_publisher = "Solus"
source_license = "solus-proprietary"
accessed_at = 2026-09-06
checked_against = [
  { title = "ATmega328P datasheet: Watchdog Timer and MCU Status Register (reset cause flags)", author = "Microchip Technology", identifier = "ATmega328P datasheet", url = "https://www.microchip.com/" },
  { title = "STM32F405/415, F407/417, F427/437, F429/439 reference manual: IWDG, WWDG, and RCC reset flags", author = "STMicroelectronics", identifier = "RM0090", url = "https://www.st.com/" },
  { title = "Zephyr Project documentation: watchdog driver API", author = "Zephyr Project", identifier = "Zephyr docs", url = "https://docs.zephyrproject.org/" },
]
+++

A hardware watchdog is a countdown timer that resets the MCU unless firmware refreshes ("kicks", "feeds") it before it expires. Its whole value is that the kick is evidence the system is healthy. The usual ways teams destroy that evidence:

- Kicking from a timer ISR. The timer keeps firing while the main loop is deadlocked, wedged in a blocking I2C read, or spinning on a corrupted state machine, so the watchdog never trips. Kick from the main loop or from a dedicated low-priority task; if that task cannot run, something higher priority is hogging the core and a reset is exactly what you want.
- Kicking unconditionally at the top of the loop. Better: each subsystem sets an "I ran this cycle" bit, and the loop kicks only when every bit is set, then clears them. A stuck serial parser then causes a reset instead of hiding behind a healthy motor loop.
- Choosing a timeout shorter than the longest legitimate blocking operation (a flash erase, a slow sensor start-up, a bootloader handshake). Measure those, add margin, and either lengthen the timeout or kick explicitly inside the long operation with a comment saying why.
- Forgetting that after a watchdog-caused reset many AVRs come up with the watchdog still enabled and set to its shortest timeout, so firmware that does not disable or reconfigure it early in start-up enters a reset loop. Bootloaders that enable a watchdog and hand over to your code have the same effect.
- Never reading the reset-cause register. The MCU records whether the last reset was power-on, brown-out, external pin, or watchdog. Log it at boot and count watchdog resets; a robot that "sometimes reboots" is usually a watchdog doing its job on a bug nobody has looked for.

What to check when a board resets mysteriously: the reset-cause flags first, then the watchdog timeout against the worst-case loop time you have actually measured, then whether any code path can block longer than the timeout with interrupts disabled.
