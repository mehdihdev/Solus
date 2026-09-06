+++
title = "A decoupling capacitor is a local charge reservoir, and loop area decides how fast it works"
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
related = ["corpus:electrical/decoupling/value-spread-bulk-vs-local", "corpus:electrical/decoupling/ceramic-dc-bias-derating"]
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
  { title = "MT-101 Decoupling Techniques", author = "Analog Devices", identifier = "MT-101", url = "https://www.analog.com/" },
  { title = "Basics of Capacitors (technical lesson series)", author = "Murata Manufacturing", identifier = "", url = "https://www.murata.com/" },
]
+++

When a digital IC switches, it draws a brief spike of current, often in a nanosecond or less. The regulator feeding the board cannot respond that fast, and the traces between regulator and IC have inductance that resists sudden changes in current. Without help, the IC's supply pin dips during each spike and the local ground bounces up, which shows up as logic glitches, ADC noise, and radiated emissions.

A decoupling capacitor sits next to the IC and supplies the spike itself, then quietly recharges from the regulator between spikes. It converts a fast, local demand into a slow, average one that the supply can meet.

How well it does this is set less by its capacitance than by the inductance of the loop the spike current flows around: from the capacitor's pad, into the IC's power pin, through the die, out the ground pin, and back to the capacitor's other pad. Inductance grows with the area enclosed by that loop. A capacitor 5 mm away on a route that runs out and back on the same layer over a solid ground plane can be a smaller loop than one 2 mm away whose ground return wanders through a via and along a slotted plane. "Place it close" is a proxy for "make the loop small".

Practical consequences: put the capacitor on the same side as the IC when possible, or directly beneath it with short vias; connect it to the power pin with a short, wide trace and to ground with its own via right at the pad; never share one via between several capacitors. The capacitor's own package inductance is part of the loop, which is why small packages outperform large ones at high frequency regardless of value.

The IC datasheet's recommended decoupling is the starting point, because the manufacturer characterised it with that network. Analog Devices' MT-101 and the capacitor vendors' technical notes cover the impedance-versus-frequency view for anyone who wants the next layer.
