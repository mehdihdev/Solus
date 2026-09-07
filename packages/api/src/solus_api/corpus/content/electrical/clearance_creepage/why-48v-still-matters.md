+++
title = "Pitfall: treating a 48 V robot bus as too low a voltage to need spacing rules"
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
related = ["corpus:electrical/clearance_creepage/clearance-vs-creepage"]
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
  { title = "IEC 60664-1 Insulation coordination for equipment within low-voltage supply systems — Principles, requirements and tests", author = "IEC", identifier = "IEC 60664-1", url = "https://www.iec.ch/" },
  { title = "IPC-2221 Generic Standard on Printed Board Design", author = "IPC", identifier = "IPC-2221", url = "https://www.ipc.org/" },
]
+++

A 48 V battery bus feels safe, and by the usual extra-low-voltage definition (below 50 V AC or 120 V ripple-free DC) it is not a shock hazard under normal conditions. Designers then carry over the spacing habits of 3.3 V logic boards. That is the mistake, for four reasons.

The voltage is not 48 V. A 13-cell lithium-ion pack is about 54.6 V at full charge, and a decelerating motor pushes the bus higher still. Clearance is judged on the peak, so the number to design to is the highest voltage the bus can ever see, plus switching transients.

DC arcs sustain themselves. An AC arc extinguishes at each zero crossing; a DC arc fed by a battery that can source hundreds of amps does not. A creepage track or a stray strand that bridges two 48 V conductors can hold an arc that burns the laminate and starts a fire, at a voltage that would never have hurt a person.

Tracking does not care about the shock threshold. Creepage failure is about leakage current across a contaminated surface, and 48 V across a dusty, humid gap on an outdoor robot will carbonise FR-4 over time just as the standards predict. Pollution degree, not nominal voltage, is what makes this a problem.

Connectors are part of the path. The pins of a wire-to-board connector, the board edge under a metal standoff, and the exposed pad under a fastener are all creepage paths; the connector's own voltage rating and the spacing to mounting hardware need the same check as the traces.

What to check: the true peak bus voltage; IPC-2221 conductor spacing for uncoated external conductors at that voltage; creepage under IEC 60664-1 for the real environment; connector voltage ratings; and fusing that can actually interrupt a DC fault, because spacing is the second line of defence, not the first.
