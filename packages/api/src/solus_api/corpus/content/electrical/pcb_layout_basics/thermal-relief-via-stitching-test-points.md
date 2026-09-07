+++
title = "Thermal relief, via stitching, and test points: three layout habits that decide manufacturability and debug"
kind = "rule_of_thumb"
audience = "reference"
applicability = []
derivation = "solus_original"
confidence = 0.8
confidence_basis = "consensus"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:electrical/grounding/where-return-current-flows", "corpus:electrical/decoupling/what-a-decoupling-capacitor-does"]
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
  { title = "IPC-2221 Generic Standard on Printed Board Design", author = "IPC", identifier = "IPC-2221", url = "https://www.ipc.org/" },
  { title = "PCB Design Guidelines for Reduced EMI", author = "Texas Instruments", identifier = "SZZA009", url = "https://www.ti.com/" },
]
+++

Thermal relief. A pad connected to a large copper plane by its full perimeter sinks heat so fast that a soldering iron or reflow oven struggles to bring the joint to temperature; the result is a cold joint or a tombstoned part. Thermal relief connects the pad through a few narrow spokes so the joint heats normally. The trade-off is that the spokes add resistance and inductance in series with the connection. Use relief on through-hole and connector pads that will be hand-soldered or reworked; use a solid connection on decoupling-capacitor ground pads, high-current vias, and the ground pins of switching regulators, where the added inductance defeats the purpose. Most CAD tools apply relief by default to every plane connection; override it deliberately for the parts that need a solid path.

Via stitching. On a multilayer board, a return current that follows a signal across a layer change has to find a via to the other reference plane, and if the nearest one is 20 mm away the loop opens up by that much. Placing ground vias near every signal via, and a grid of ground vias across the board and along its edges, gives returns a short path and ties the planes to one potential. Stitch the edge of a board densely under any RF or high-speed section and around the perimeter of a slot.

Test points. Every rail, every bus clock and data line, reset, and a few grounds should have a probe point that is not a fine-pitch component lead: a pad, a loop, or a 1 mm exposed via. Decide this when the schematic is drawn, because at layout time there is never room. Place ground test points near signal ones so a probe's ground lead can be short; a 100 mm scope ground lead turns a clean 3.3 V rail into apparent noise.

Limits: thermal relief geometry (spoke count and width) should follow the fab's capability and IPC-2221 guidance; the number of stitching vias is a judgment call that trades cost and routing space against return-path quality.
