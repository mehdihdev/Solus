+++
title = "I2C speed modes, rise-time limits, bus capacitance limit, and pull-up range"
kind = "reference_value"
audience = "reference"
applicability = [{ key = "bus", value = "i2c" }]
derivation = "solus_original"
confidence = 0.9
confidence_basis = "vendor_stated"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:electrical/signal_integrity/i2c-pullups-and-bus-capacitance"]
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

Values per the NXP I2C-bus specification (UM10204); the specification governs where this table and a datasheet disagree.

| Mode | Max bit rate | Max SDA/SCL rise time | Max bus capacitance | Min low-level sink current |
| --- | --- | --- | --- | --- |
| Standard-mode | 100 kbit/s | 1000 ns | 400 pF | 3 mA |
| Fast-mode | 400 kbit/s | 300 ns | 400 pF | 3 mA |
| Fast-mode Plus | 1 Mbit/s | 120 ns | 550 pF | 20 mA |

The maximum output low voltage the sink current is specified at is 0.4 V (for bus voltages above 2 V).

Pull-up bounds:

```
R_max = t_rise_max / (0.8473 · C_bus)
R_min = (V_DD − V_OL_max) / I_OL        (V_OL_max = 0.4 V)
```

Worked values, Fast-mode at 3.3 V:

| Estimated C_bus | R_max |
| --- | --- |
| 50 pF | about 7.1 kΩ |
| 100 pF | about 3.5 kΩ |
| 200 pF | about 1.8 kΩ |
| 400 pF | about 0.9 kΩ (at the capacitance limit, the minimum resistor is also about 0.97 kΩ, so there is no margin left) |

R_min at 3.3 V with 3 mA sink is about 0.97 kΩ; at 5 V about 1.5 kΩ.

Estimating C_bus: roughly 10 pF per device pin plus the trace or cable capacitance; ordinary ribbon or hook-up wire is on the order of 50–100 pF per metre, so a 1 m cable alone can consume most of the 400 pF budget. Measure with a scope if the edge looks rounded.

Common choice: 4.7 kΩ for a short bus with a few devices at 100 kbit/s; 2.2 kΩ for Fast-mode with more devices or a short harness. Breakout boards often ship with their own pull-ups; three breakouts each with 4.7 kΩ present about 1.6 kΩ in parallel, already close to R_min at 3.3 V, so remove the extras when stacking modules.
