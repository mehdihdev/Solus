+++
title = "What a 1 oz outer-layer trace carries, per TI's power-controller layout note"
kind = "reference_value"
audience = "reference"
applicability = [{ key = "process", value = "pcb_2l" }]
derivation = "facts_extracted"
confidence = 0.85
confidence_basis = "vendor_stated"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:electrical/trace_width_current/why-width-and-copper-set-current", "corpus:electrical/trace_width_current/ti-slua366-design-etch-for-the-maximum-current"]
further_reading = []
corpus_version = "0.2.0"
revised_in = "0.2.0"

[provenance]
source_class = "vendor_documentation"
source_title = "PCB Layout Guidelines for Power Controllers (SLUA366)"
source_publisher = "Texas Instruments"
source_url = "https://www.ti.com/lit/ug/slua366/slua366.pdf"
source_locator = "October 2005, p. 1 Table 1 and p. 2 §2.2–2.3"
source_license = "vendor-terms"
accessed_at = 2026-09-06
attribution = "Texas Instruments, SLUA366, October 2005, p. 1 Table 1 and p. 2 §2.2–2.3"
+++

TI's application report SLUA366 gives a compact rule set for how much current a printed-circuit
etch can carry. The facts below are extracted from it with their stated conditions; the full
table is the publisher's and is not reproduced here.

The conditions the note states for its capacity figures: 1 oz/ft² copper (0.035 mm thick), a
10 °C rise on outer layers and 20 °C on inner layers, groups of high-current tracks derated,
and tracks not near or over heatsink areas.

Two representative values from the note, under those conditions: a 0.050 in (1.27 mm) wide
outer-layer etch carries about 3.2 A, and a 0.100 in (2.54 mm) etch about 6.0 A. So the answer
to "what width for 3 A on 1 oz copper" under this note's assumptions is a little under 0.050 in,
roughly 1.2 mm, on an outer layer with a 10 °C rise budget.

Two scaling rules the note states: each doubling of copper thickness raises capacity by about
sqrt(2), roughly 1.4×, and each doubling of a single track's width raises it by about 1.65×.
Width therefore buys more than thickness, and both are sub-linear because a wider or thicker
conductor sheds heat less efficiently per unit of cross-section.

Vias: the note treats a standard 10 mil (0.25 mm) inner-ring feedthrough as carrying about 1 A,
so a power path that crosses layers needs roughly one via per ampere, and vias add inductance
between supply and load as well.

The note's own worked example: a circuit specified for a 12 A minimum is designed for 18 A, and
at 1 oz copper that needs a minimum etch width of 0.35 in for a 10 °C outer-layer rise, with 18
feedthroughs to bring power up from an inner plane.

Limits: these are one vendor's layout guidelines for a specific temperature-rise budget, not a
standard. The IPC-2221 and IPC-2152 methods relate current, temperature rise, copper area,
and board conditions more generally; consult the standard for anything outside these
assumptions, and derate for bundled traces, enclosed boards, and elevated ambient.
