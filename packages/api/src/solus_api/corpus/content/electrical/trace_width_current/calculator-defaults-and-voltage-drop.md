+++
title = "Pitfall: trusting a trace-width calculator's defaults and ignoring voltage drop"
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
related = ["corpus:electrical/trace_width_current/why-width-and-copper-set-current"]
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
  { title = "IPC-2152 Standard for Determining Current Carrying Capacity in Printed Board Design", author = "IPC", identifier = "IPC-2152", url = "https://www.ipc.org/" },
  { title = "Analog Engineer's Pocket Reference", author = "Texas Instruments", identifier = "SLYW038", url = "https://www.ti.com/" },
]
+++

The usual failure: someone opens a trace-width calculator, leaves the default temperature rise, copper weight, and ambient in place, reads off a width, and treats it as the trace's rating. Three things go wrong.

First, the default rise is often a comfortable value for an open board on a bench. Inside a sealed robot chassis at 45 °C ambient, next to a motor driver, the same rise puts the copper at a temperature the neighbouring MLCCs and connectors were not derated for. Enter the real ambient and pick the rise deliberately.

Second, capacity is set by the narrowest point. A wide trace that necks down to pass between two connector pads, or lands on a pad with thermal-relief spokes, is rated by the neck. Check every segment, including the copper under the connector.

Third, heating is not the only limit. A trace that will not overheat can still drop too much voltage. Resistance is:

```
R = ρ · L / (w · t)        ρ_Cu ≈ 1.7 × 10⁻⁸ Ω·m at 20 °C
```

and copper's resistance rises about 0.4 % per kelvin, so a warm trace drops more. A 200 mm run of 1 mm wide, 1 oz (35 µm) trace is about 0.1 Ω; at 3 A that is 0.3 V, which on a 3.3 V rail feeding a sensor is a real error, and 0.9 W of heat you did not budget. For long, high-current runs, voltage drop usually forces a wider trace before temperature does.

What to check: ambient and rise entered, not defaulted; every neck and pad; drop at full current against the rail's tolerance; and whether a plane or heavier copper is cheaper than a very wide trace. IPC-2152 is the method to confirm against.
