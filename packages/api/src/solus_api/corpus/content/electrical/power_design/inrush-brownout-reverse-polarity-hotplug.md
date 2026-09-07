+++
title = "Pitfalls at the power input: inrush, brown-out resets, reversed polarity, and hot-plugging"
kind = "pitfall"
audience = "reference"
applicability = []
derivation = "solus_original"
confidence = 0.85
confidence_basis = "vendor_stated"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:electrical/power_design/ldo-vs-buck-vs-boost", "corpus:electrical/connector_selection/connector-pitfalls"]
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
  { title = "Reverse Current/Battery Protection Circuits", author = "Texas Instruments", identifier = "", url = "https://www.ti.com/" },
  { title = "TPS2660x industrial eFuse datasheet", author = "Texas Instruments", identifier = "", url = "https://www.ti.com/" },
]
+++

Inrush. Every bulk capacitor on the bus is a short circuit for the instant power is applied (I = C · dV/dt). Plugging a charged battery into a board with a few thousand microfarads draws a current spike limited only by wiring resistance: the connector sparks and pits, the battery protector may trip, and an upstream fuse or bench supply can fold back. Fixes: an eFuse or hot-swap controller with a programmed slew rate, an NTC or resistor-plus-bypass-FET soft start, an anti-spark connector variant with a pre-charge resistor, or simply less bulk capacitance where a buck converter does not need it.

Brown-out. A servo or motor stall draws many times its running current, the 5 V rail dips for a few milliseconds, and the MCU's brown-out detector resets it. The symptom is a robot that reboots when it starts moving. Check the rail with a scope on single-shot trigger, not a multimeter. Fixes: power motors and logic from separate regulators fed from the battery, not one shared 5 V; bulk capacitance close to the logic regulator; a brown-out threshold set deliberately; and current limiting on the motor side.

Reversed polarity. Keyed connectors are the first defence and cost nothing. A series diode protects but drops its forward voltage at full current (0.5–1 W per ampere for a silicon diode). A P-channel MOSFET wired as an ideal diode drops millivolts and is the standard answer for battery inputs. A reverse diode across the input with a fuse in series is sacrificial: it works once and blows the fuse. Nothing here protects against a reversed connector that also mates with a different-voltage supply; keep connector families distinct per voltage.

Hot-plugging. Connectors that mate power before ground, or let a signal pin touch first, drive current through I/O pins. Use connectors with first-mate/last-break ground, or an eFuse with under-voltage lockout so the load is only enabled after the input is stable.
