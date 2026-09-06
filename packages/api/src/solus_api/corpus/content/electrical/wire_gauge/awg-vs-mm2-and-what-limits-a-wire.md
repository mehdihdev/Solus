+++
title = "AWG versus mm², and the two things that actually limit a wire: heat and voltage drop"
kind = "principle"
audience = "fundamentals"
applicability = []
derivation = "solus_original"
confidence = 0.9
confidence_basis = "consensus"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:electrical/wire_gauge/ampacity-vs-voltage-drop", "corpus:electrical/wire_gauge/stranded-vs-solid-crimp-vs-solder"]
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
  { title = "Analog Engineer's Pocket Reference", author = "Texas Instruments", identifier = "SLYW038", url = "https://www.ti.com/" },
  { title = "NASA-STD-8739.4 Workmanship Standard for Crimping, Interconnecting Cables, Harnesses, and Wiring", author = "NASA", identifier = "NASA-STD-8739.4", url = "https://standards.nasa.gov/" },
]
+++

American Wire Gauge runs backwards: a larger number is a thinner wire. The scale is geometric, so every 3 gauge steps roughly halves (or doubles) the cross-sectional area, and every 6 steps halves or doubles the diameter. Metric practice states the conductor area in mm² directly. Conversions for the sizes that appear in robots, solid copper at 20 °C (stranded conductors of the same nominal gauge measure a few percent higher resistance):

| AWG | Diameter | Area | Resistance |
| --- | --- | --- | --- |
| 10 | 2.59 mm | 5.26 mm² | 3.3 mΩ/m |
| 12 | 2.05 mm | 3.31 mm² | 5.2 mΩ/m |
| 14 | 1.63 mm | 2.08 mm² | 8.3 mΩ/m |
| 16 | 1.29 mm | 1.31 mm² | 13.2 mΩ/m |
| 18 | 1.02 mm | 0.82 mm² | 21.0 mΩ/m |
| 20 | 0.81 mm | 0.52 mm² | 33.3 mΩ/m |
| 22 | 0.64 mm | 0.33 mm² | 53.0 mΩ/m |
| 24 | 0.51 mm | 0.20 mm² | 84.2 mΩ/m |
| 26 | 0.40 mm | 0.13 mm² | 134 mΩ/m |
| 28 | 0.32 mm | 0.08 mm² | 213 mΩ/m |

A wire has two independent limits. The first is thermal: current heats the copper, and the insulation has a temperature rating (PVC around 80–105 °C, silicone and PTFE higher) it must stay under, given the ambient and how many other warm wires are bundled with it. This is what an ampacity table expresses, and it is always stated for conditions: free air or bundled, a particular insulation, a particular ambient. The second is voltage drop: resistance times current times the round-trip length, which is a problem long before the wire is warm when the rail is 5 V and the load is a servo at the end of two metres of harness.

In a robot, runs are short and currents are spiky, so voltage drop and the current rating of the connector on each end usually govern before the insulation temperature does. Choose the gauge for the drop budget, then confirm it against the thermal limit for how the wire is actually installed.
