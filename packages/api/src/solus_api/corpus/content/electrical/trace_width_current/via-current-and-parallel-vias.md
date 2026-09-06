+++
title = "Sizing vias for current: match barrel cross-section to the trace"
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
  { title = "IPC-2221 Generic Standard on Printed Board Design", author = "IPC", identifier = "IPC-2221", url = "https://www.ipc.org/" },
]
+++

A via carries current through a thin plated cylinder, not through the drilled hole. Its conducting cross-section is roughly the circumference of the drill times the plating thickness:

```
A_via ≈ π · d_drill · t_plating
```

Plating is thin, on the order of tens of micrometres and set by the fab's process class, so a via is a much smaller conductor than it looks. A 0.3 mm drill with 25 µm plating is about 0.024 mm² of copper, which is less than a 1 mm wide trace in 1 oz copper (about 0.035 mm²).

The defensible default: give a high-current net enough vias that their combined barrel area is at least equal to the cross-section of the trace feeding them, and spread them so each carries a similar share. Vias into a plane are cooled well by the surrounding copper, so this is conservative; a cluster of vias spaced closer than their own diameter shares heat and gains less than the count suggests. Current does not divide perfectly evenly between parallel vias, so add one more than the arithmetic says on anything that matters.

Limits of the rule: it is a cross-section argument, and IPC-2152's finding is that cooling dominates, so a via's real capacity depends on the planes around it and the board's thermal path. Ask the fab for the plating thickness they guarantee before you count on it, and confirm with the IPC-2152 method for the actual copper weight and layer count. Use it for power and motor-phase nets; signal vias never need this analysis.
