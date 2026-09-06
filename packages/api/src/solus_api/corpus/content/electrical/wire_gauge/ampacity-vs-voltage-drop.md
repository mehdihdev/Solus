+++
title = "Sizing a robot's wire: budget the voltage drop first, then check ampacity under real conditions"
kind = "rule_of_thumb"
audience = "reference"
applicability = []
derivation = "solus_original"
confidence = 0.8
confidence_basis = "rule_of_thumb"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:electrical/wire_gauge/awg-vs-mm2-and-what-limits-a-wire"]
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
  { title = "SAE AS50881 Wiring Aerospace Vehicle", author = "SAE International", identifier = "AS50881", url = "https://www.sae.org/" },
  { title = "Analog Engineer's Pocket Reference", author = "Texas Instruments", identifier = "SLYW038", url = "https://www.ti.com/" },
]
+++

The procedure that avoids both undersized and absurdly oversized harnesses:

1. Take the continuous current and the peak current separately. Motors stall at several times running current; size the thermal check on continuous and the drop check on peak, because the drop matters most at the moment the motor starts.

2. Compute the drop over the round trip. Current flows out and back, so the length is twice the run:

```
ΔV = I · R_per_metre · 2L
P_heat = I² · R_per_metre · 2L
```

Example: 2 m of 18 AWG (about 21 mΩ/m) to a motor drawing 10 A gives 0.42 V of drop and 4.2 W of heat spread along the wire. On a 24 V bus that is under 2 % and fine; on a 5 V rail it would be an 8 % sag that also carries the motor's current noise straight into the logic's reference.

3. Set the drop budget from the load. Logic and sensor rails tolerate very little (a few percent, or less if an analog reference is downstream); motor buses tolerate more, since the drive regulates anyway, but the lost power is heat in the harness.

4. Then check ampacity for the installation. Free-air ratings are far higher than ratings for a wire bundled with others inside a warm enclosure; standards such as SAE AS50881 derate for bundle size and ambient, and manufacturers publish curves for their insulation. Do not take a single "18 AWG = X amps" number from a chart without reading which case it describes.

5. Check the connector last. The contact's rated current for that wire size is frequently the binding limit, and it is derated further when many pins in the same housing are loaded.

Limits of the rule: it assumes copper conductors and ignores skin effect, which is irrelevant at motor PWM frequencies for these gauges. Aluminium wire, high-temperature environments, or wires inside potting need their own analysis.
