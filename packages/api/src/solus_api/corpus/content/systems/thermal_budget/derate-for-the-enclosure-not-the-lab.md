+++
title = "Derate for the hottest corner of the enclosure, then check the airflow path"
kind = "rule_of_thumb"
audience = "reference"
applicability = []
derivation = "solus_original"
confidence = 0.75
confidence_basis = "rule_of_thumb"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:systems/thermal_budget/junction-to-ambient-chain", "corpus:systems/thermal_budget/theta-ja-is-a-test-board-number"]
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
  { title = "MT-093 Tutorial: Thermal Design Basics", author = "Analog Devices", identifier = "MT-093", url = "https://www.analog.com/" },
  { title = "Jetson module thermal design guides", author = "NVIDIA", identifier = "Jetson Download Center thermal design guides", url = "https://developer.nvidia.com/" },
  { title = "Aluminum electrolytic capacitor lifetime and temperature application notes", author = "Vishay", identifier = "aluminum electrolytic capacitor technical notes", url = "https://www.vishay.com/" },
]
+++

Rules of thumb for thermal derating in a robot, each with the condition it holds under.

Design against the internal air temperature at the worst duty, not the bench. Datasheet ratings are quoted at a stated ambient, usually 25 degrees Celsius; every degree the enclosure's interior runs above that comes straight off the headroom to the junction limit. A robot that is warm to the touch in a 22 degree lab is over its limits in a 35 degree afternoon in direct sun, because the sun adds to the wall temperature before the electronics add anything.

Read the derating curve, not the headline. Regulators, drivers, and connectors publish output current versus ambient temperature; the flat part of that curve ends well before the maximum ambient. Budget at the current the curve gives for your worst internal temperature.

Airflow needs a path, not a fan. A fan in a box with no outlet stirs the air and moves very little heat out. Air must enter, pass over the hot parts, and leave; place the inlet low and the outlet high so natural convection helps, and make sure the fan's pressure capability exceeds the resistance of filters, grilles, and the crowded interior. A dust filter that is never cleaned turns a ventilated enclosure into a sealed one.

Sealed enclosures shed heat through their walls. Mount drivers and regulators to the metal chassis or a wall through a thermal interface so the chassis is the heatsink, and give the heat-producing parts and the battery different walls.

Hot electrolytic capacitors age fast. Capacitor vendors publish the rated lifetime at the rated temperature and note that lifetime roughly doubles for each 10 kelvin the capacitor runs below that rating, and halves for each 10 kelvin above; this holds for aluminium electrolytic capacitors and is the usual reason a power board that "works" has a life of one summer.

Compute modules need a designed thermal solution. Vendors such as NVIDIA publish thermal design guides for their modules that assume a heatsink or fan sized for the chosen power mode; running a module at its highest power mode with a passive heatsink chosen for a lower one leads to throttling that looks like a software performance bug.

Measure. After the arithmetic, run the robot at worst-case duty in the warmest environment you can arrange, log case temperatures with thermocouples, and keep the log as the baseline for future changes.
