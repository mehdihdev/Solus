+++
title = "Trace current capacity is a temperature-rise problem, not a fixed ampacity"
kind = "principle"
audience = "fundamentals"
applicability = []
derivation = "solus_original"
confidence = 0.9
confidence_basis = "standard_derived"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:electrical/trace_width_current/via-current-and-parallel-vias", "corpus:electrical/trace_width_current/calculator-defaults-and-voltage-drop"]
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
  { title = "IPC-2152 Standard for Determining Current Carrying Capacity in Printed Board Design", author = "IPC", identifier = "IPC-2152", url = "https://www.ipc.org/" },
]
+++

A copper trace has no single "maximum current". Current through its resistance produces heat (I squared times R), the trace warms until it sheds that heat to the board and the air, and the question a designer actually answers is: how much hotter than ambient am I willing to let this copper get? Pick a temperature rise, and the allowable current follows from the trace's cross-section and how well it is cooled.

Cross-section is width times copper thickness. Copper weight is quoted in ounces per square foot; the common 1 oz foil is about 35 µm thick, 2 oz about 70 µm. Doubling the copper weight buys roughly the same capacity as doubling the width, which is why high-current boards often specify heavier copper instead of very wide traces.

Cooling is the part people forget. A trace on an outer layer loses heat to the air and through the laminate; an inner trace can only conduct into the laminate and neighbouring copper. IPC-2221 handled this with separate external and internal curves and a conservative derating for internal layers. IPC-2152 replaced assumption with measurement and showed that what surrounds the trace matters as much as which layer it is on: nearby copper planes, board thickness, and whether the board sits in still air or a vacuum all move the result substantially. A trace next to a large plane runs cooler than the same trace on a bare board.

How to use this: decide on an acceptable rise (a small rise for anything near temperature-sensitive parts or in a sealed enclosure, larger where the board is open and nothing nearby cares), pick copper weight from the fab's standard offering, then size width using the IPC-2152 method or a calculator that implements it, entering your real conditions rather than the defaults. Treat the result as one segment of the thermal design of the enclosure, not as a standalone number. For the tables themselves, consult the standards; this corpus states the principle only.
