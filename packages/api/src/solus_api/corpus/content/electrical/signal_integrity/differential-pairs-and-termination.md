+++
title = "CAN, RS-485, and USB: why differential pairs need termination and where it goes"
kind = "rule_of_thumb"
audience = "reference"
applicability = []
derivation = "solus_original"
confidence = 0.9
confidence_basis = "standard_derived"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:electrical/signal_integrity/spi-clock-uart-levels-level-shifting", "corpus:electrical/bus_addressing/can-id-allocation-and-spi-chip-select"]
further_reading = [
  { title = "High-Speed Digital Design: A Handbook of Black Magic", author = "Johnson, Graham", identifier = "ISBN 978-0133957242" },
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
  { title = "Introduction to the Controller Area Network (CAN)", author = "Texas Instruments", identifier = "SLOA101", url = "https://www.ti.com/" },
  { title = "The RS-485 Design Guide", author = "Texas Instruments", identifier = "SLLA272", url = "https://www.ti.com/" },
  { title = "ISO 11898-2 Road vehicles — Controller area network (CAN) — High-speed physical medium access unit", author = "ISO", identifier = "ISO 11898-2", url = "https://www.iso.org/" },
  { title = "Universal Serial Bus Specification, Revision 2.0", author = "USB Implementers Forum", identifier = "", url = "https://www.usb.org/" },
]
+++

A differential pair carries the signal as the difference between two wires. Noise that couples into the cable hits both wires almost equally and cancels at the receiver, which is why CAN, RS-485, and USB survive metres of cable in a robot when I2C and SPI do not. But a pair is a transmission line: an edge travelling down it reflects from any point where the impedance changes, most of all an open end, and the reflection arrives back as a spurious edge. Termination places a resistor equal to the line's characteristic impedance at the end so the energy is absorbed instead of reflected.

CAN (ISO 11898-2). Linear bus topology, one 120 Ω resistor across CANH and CANL at each of the two physical ends, and nowhere else. The quick health check: with power off, the resistance between CANH and CANL should read about 60 Ω; 120 Ω means one terminator is missing, 40 Ω means someone added a third. Keep stubs from the bus to each node short. A CAN bus with no or one terminator often works at low bit rates on the bench and fails in the field.

RS-485. Same rule: 120 Ω at both ends of the cable (typical twisted pair is close to that), nodes hang off the line with short stubs. Add fail-safe biasing so the receivers see a defined idle state when no driver is active, and run a third conductor for ground reference between nodes, since the receivers have a limited common-mode range and two chassis at different potentials will exceed it. The A/B labelling is inconsistent between manufacturers; if the link is dead, swap them before debugging further. TI's SLLA272 covers biasing, cable length versus data rate, and isolation.

USB 2.0. The pair is specified at 90 Ω differential impedance, terminated inside the transceivers, so the designer's job is the trace: route D+ and D− as a coupled pair of controlled impedance over a solid reference plane, match their lengths, avoid stubs and vias, and never run high-speed USB through a 2.54 mm header.

Limits: termination values assume the standard cable; a non-standard cable with a different impedance needs matching resistors. Terminating in the middle of a bus, or terminating every node, loads the drivers and breaks the link.
