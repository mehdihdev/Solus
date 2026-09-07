+++
title = "Test firmware logic off-target: put the hardware behind an interface and mock it"
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
related = ["corpus:software/embedded_patterns/superloop-vs-rtos", "corpus:software/real_time_constraints/delay-in-a-control-loop"]
corpus_version = "0.1.0"
revised_in = "0.1.0"

[provenance]
source_class = "solus_authored"
source_title = "Solus engineering corpus"
source_publisher = "Solus"
source_license = "solus-proprietary"
accessed_at = 2026-09-06
checked_against = [
  { title = "Zephyr Project documentation: Test Framework (ztest), native_sim board, and the logging subsystem", author = "Zephyr Project", identifier = "Zephyr docs", url = "https://docs.zephyrproject.org/" },
  { title = "PlatformIO documentation: Unit Testing (native and embedded test runners)", author = "PlatformIO Labs", identifier = "PlatformIO docs, Unit Testing", url = "https://docs.platformio.org/" },
]
+++

Most firmware bugs are not in the register writes; they are in the logic above them: the state machine that sequences a homing move, the parser that reassembles packets, the controller arithmetic. That logic can run on your laptop in milliseconds if the hardware is kept out of it.

The pattern: split every module into a pure core and a thin hardware layer. The core takes inputs as values (a byte, an encoder count, a timestamp) and produces outputs as values or through a small interface (a struct of function pointers in C, an abstract class in C++). The hardware layer implements that interface with real register access. On the host you compile the core against a mock that records what was called and feeds scripted inputs; on the target you link the real implementation. Time is an input like any other: pass the tick into the function instead of calling `millis()` inside it, and a test can jump the clock forward to hit a timeout in microseconds of wall time.

What this buys you: tests run in CI on every commit with no board attached; edge cases that are painful to provoke on hardware (a checksum failure exactly at buffer wrap, a sensor that returns the same value forever, a timer that overflows) become one-line fixtures; and the suite documents intended behaviour for the next person.

Tooling that fits: Zephyr's ztest with its `native_sim` board runs the application as a Linux process against the same kernel API, so even thread and timer logic can be exercised off-target. PlatformIO's unit-test runner builds the same test source for the native platform and for the board, so a test can be promoted to on-target without a rewrite. Plain CMake with any C or C++ test framework works for the pure core.

Limits: off-target tests do not catch timing, interrupt-priority, peripheral-configuration, or electrical problems. Keep a smaller on-target suite, or a hardware-in-the-loop rig that drives the real inputs, for those. A test that passes on the host and fails on the board is telling you the mock differs from the hardware; fix the mock's model first, then the code.

On logging: a `printf` in the control path costs tens to hundreds of microseconds on a UART and reorders timing. Log into a RAM ring buffer and drain it from a low-priority task, or use a deferred logger (Zephyr's logging subsystem works this way by default), so that instrumentation does not change the behaviour under test.
