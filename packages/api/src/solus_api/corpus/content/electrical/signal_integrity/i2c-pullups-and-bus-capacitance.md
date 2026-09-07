+++
title = "Why I2C needs pull-ups, and why bus capacitance sets how fast it can go"
kind = "principle"
audience = "fundamentals"
applicability = [{ key = "bus", value = "i2c" }]
derivation = "solus_original"
confidence = 0.9
confidence_basis = "vendor_stated"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:electrical/signal_integrity/i2c-pullup-reference-values", "corpus:electrical/bus_addressing/i2c-addresses-and-conflicts"]
further_reading = []
corpus_version = "0.1.0"
revised_in = "0.1.0"

[provenance]
source_class = "solus_authored"
source_title = "Solus engineering corpus"
source_publisher = "Solus"
source_license = "solus-proprietary"
accessed_at = 2026-09-06
checked_against = [
  { title = "I2C-bus specification and user manual", author = "NXP Semiconductors", identifier = "UM10204", url = "https://www.nxp.com/" },
  { title = "I2C Bus Pull-Up Resistor Calculation", author = "Texas Instruments", identifier = "SLVA689", url = "https://www.ti.com/" },
]
+++

I2C uses two wires, SDA and SCL, and every device on them has an open-drain output: it can pull the line to ground, or let go. Nothing on the bus ever drives the line high. That is what lets many devices share the wires without fighting, and it is why the bus does not work at all without pull-up resistors: the resistors are the only thing that returns a line to the high state after a device releases it.

The consequence is an asymmetry. A falling edge is fast, because a transistor is pulling the line down. A rising edge is an RC charge: the pull-up resistor charging the total capacitance of the bus wiring, the pins of every device, and the connectors. The larger the resistor or the more capacitance, the slower the rise, and if the line has not reached a valid high before the next clock edge the receiver samples garbage. That shows up as NACKs, corrupted reads, and a bus that works on the bench with one sensor but fails with four sensors on a half-metre cable.

The NXP specification (UM10204) expresses this as a maximum rise time for each speed mode and a maximum bus capacitance of 400 pF for the standard and fast modes. Rise time is the resistor times the capacitance times a constant, so once you estimate the capacitance the maximum usable pull-up follows directly:

```
R_pullup_max = t_rise_max / (0.8473 · C_bus)
```

There is a lower limit too. When a device pulls the line low, the pull-up's current flows through its output transistor, and the specification limits how much current a device must sink while holding a valid low level. A smaller resistor gives faster edges but eventually exceeds that current.

Practical reading: a long I2C cable is the wrong tool, because capacitance grows with length and the bus has no termination scheme. Keep I2C on the board or on a short harness; for anything longer, use a bus buffer/extender, or a differential bus such as CAN or RS-485. Texas Instruments' SLVA689 walks through the pull-up arithmetic with worked examples.
