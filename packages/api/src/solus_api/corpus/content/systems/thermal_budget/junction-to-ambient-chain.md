+++
title = "Heat flows from junction to ambient through a chain of thermal resistances"
kind = "principle"
audience = "fundamentals"
applicability = []
derivation = "solus_original"
confidence = 0.9
confidence_basis = "vendor_stated"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:systems/thermal_budget/theta-ja-is-a-test-board-number", "corpus:systems/thermal_budget/derate-for-the-enclosure-not-the-lab"]
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
  { title = "Semiconductor and IC Package Thermal Metrics", author = "Texas Instruments", identifier = "SPRA953", url = "https://www.ti.com/" },
  { title = "MT-093 Tutorial: Thermal Design Basics", author = "Analog Devices", identifier = "MT-093", url = "https://www.analog.com/" },
]
+++

Every semiconductor has a maximum junction temperature in its datasheet, and the junction is the one place you cannot put a thermometer. What you can do is treat heat like current: power dissipated in the die flows out through a series of thermal resistances, each in kelvin per watt, and the temperature rises across each one in proportion to the power passing through it.

```
T_junction = T_ambient + P_dissipated × (θ_junction-to-case + θ_case-to-sink + θ_sink-to-ambient)
```

Three consequences follow.

The ambient that matters is the air touching the part, inside your enclosure, at the hottest point of the mission, not the room. A driver that has 40 kelvin of headroom on the bench at 22 degrees Celsius has 25 kelvin outdoors at 37 degrees, and less again once the enclosure's internal air has warmed by another 15 kelvin from everything else in it.

The chain is only as good as its worst link. A big heatsink bolted on with no thermal interface material, or a package whose thermal pad is not soldered to a copper area with vias to the other layers, puts a large resistance right at the start of the path, and nothing downstream can compensate.

In a sealed robot the heat has to leave by conduction and then by the outside of the enclosure, because there is no through-flow of air. Inside, the air only moves heat from the hot parts to the walls; the walls then shed it to the outside by convection and radiation. Motor drivers, motors, regulators, and the compute module are usually the dominant sources, and the batteries are the most temperature-sensitive occupants. The practical design move is to mount the dissipating parts on the metal chassis or on an enclosure wall through a thermal interface, so the chassis becomes the heatsink, and to keep the battery away from those walls.

Do the arithmetic with datasheet maximum dissipation, not typical, then measure the case temperature under worst-case load and back-compute the junction temperature from the vendor's junction-to-case or junction-to-top figures. If the measurement disagrees with the arithmetic, believe the measurement.
