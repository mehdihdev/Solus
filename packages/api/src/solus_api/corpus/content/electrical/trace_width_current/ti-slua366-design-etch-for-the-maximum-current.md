+++
title = "Size power etch for the maximum current the circuit can actually deliver"
kind = "procedure"
audience = "fundamentals"
applicability = []
derivation = "summary"
confidence = 0.85
confidence_basis = "vendor_stated"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:electrical/trace_width_current/ti-slua366-etch-current-for-1oz-copper"]
further_reading = []
corpus_version = "0.2.0"
revised_in = "0.2.0"

[provenance]
source_class = "vendor_documentation"
source_title = "PCB Layout Guidelines for Power Controllers (SLUA366)"
source_publisher = "Texas Instruments"
source_url = "https://www.ti.com/lit/ug/slua366/slua366.pdf"
source_locator = "October 2005, §2.1–2.7"
source_license = "vendor-terms"
accessed_at = 2026-09-06
attribution = "Texas Instruments, SLUA366, October 2005, §2.1–2.7"
+++

The layout note TI wrote for its hot-plug power controllers is short and its advice generalises
to any board that routes real current. In Solus's words:

Design the copper for the worst case, not the nameplate. A controller's current-limit
comparator has a tolerance, so a channel specified to deliver at least a given current will in
practice deliver more before it trips. The note's example is a 12 A minimum channel that must be
laid out for 18 A: every etch run and every via on that path is sized for the higher figure.

Keep the controller, the pass MOSFET, and the sense resistor together at the load. The sense
resistor should be as close to a direct connection between the MOSFET and the load as the
layout allows, and its two sense traces should leave from the resistor's own pads and run as a
pair to the controller (a Kelvin connection), so the controller measures the voltage across the
resistor and not across a stretch of copper.

Put bypass capacitors on the same side of the board as the part they serve, as close as
possible, without vias in the path where you can avoid it. Vias add inductance; at tens of MHz
the note considers bypassing through vias close to ineffective, and several vias in parallel are
sometimes needed just to bring the inductance down.

Expect transients. High-current switching puts voltage spikes across the sense resistor; a small
capacitor at the controller's sense inputs (the note uses 1 nF to filter above about 1 MHz) is
often needed, chosen from the impedance-versus-frequency behaviour of the capacitor rather than
by habit.

Bulk capacitance is sized from the surge: C = I × Δt / ΔV, where I is the surge current, Δt its
duration, and ΔV the drop the load can tolerate. Place bulk at the MOSFET input and again at the
load, with high-frequency bypass beside it.

Why it matters in a robot: motor rails and hot-pluggable modules behave exactly like the note's
backplane slots. Undersized etch shows up as heat and voltage drop under stall; a sense trace
that shares copper with the load current shows up as a controller that trips at the wrong
current.
