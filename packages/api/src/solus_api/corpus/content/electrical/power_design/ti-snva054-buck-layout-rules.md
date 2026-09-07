+++
title = "Buck converter layout: the AC loop, the eight rules, and why an inch matters"
kind = "procedure"
audience = "reference"
applicability = []
derivation = "summary"
confidence = 0.9
confidence_basis = "vendor_stated"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:electrical/power_design/ldo-vs-buck-vs-boost", "corpus:electrical/decoupling/what-a-decoupling-capacitor-does"]
further_reading = []
corpus_version = "0.2.0"
revised_in = "0.2.0"

[provenance]
source_class = "vendor_documentation"
source_title = "AN-1229 SIMPLE SWITCHER PCB Layout Guidelines (SNVA054C)"
source_publisher = "Texas Instruments"
source_url = "https://www.ti.com/lit/pdf/snva054"
source_locator = "June 2002, revised April 2013, §2–3"
source_license = "vendor-terms"
accessed_at = 2026-09-06
attribution = "Texas Instruments, SNVA054C, June 2002, revised April 2013, §2–3"
+++

TI's AN-1229 explains why switching-regulator layouts fail and gives a rule list for a buck.
Restated in Solus's words.

The idea. In a buck converter some traces carry a current that steps abruptly every switching
edge: the input capacitor to the switch, the switch to the catch diode, the diode's return. Those
are the AC sections. Copper is barely resistive but it is inductive, and the note's thumb rule is
about 20 nH per inch of trace. A resistive drop of a few millivolts is harmless; the inductive
kick V = L·di/dt during a 30 ns edge is not, and it is what makes controllers misbehave. The
current step is not small either: the note puts it at roughly 1.2× the load current at
switch turn-off and 0.8× at turn-on for a well-designed inductor, with transitions of about
30 ns for fast FET switchers and 75 ns for slower bipolar ones. Fast parts therefore need tighter
layouts, not looser.

The rules, for a buck:

1. Place the catch diode and the input capacitor right at the IC, so the AC loop is as small as
   the packages allow.
2. Do not omit a small ceramic input bypass (the note's range is 0.1–0.47 µF) on fast devices,
   even when a bulk input capacitor is present.
3. Use a ground plane where one exists and tie the return nodes to it with vias.
4. Vias under a power device's tab are thermal vias: size them correctly or place them next to
   the tab, or assembly suffers.
5. Route the feedback trace away from the inductor and the diode; it is the most noise-sensitive
   net on the board.
6. Do not widen the switching-node copper beyond what current needs: it is an antenna.
7. If the diode needs a large heatsink area, isolate it as the note describes rather than
   flooding copper on the switch node.
8. For higher-power surface-mount designs, prefer 2 oz copper: it manages heat with less area.

The exception the note flags: copper filling helps parasitic inductance and IC noise but can
increase EMI, so it is not an unconditional good.

Why it matters in a robot: a motor-controller board typically has a buck feeding logic a few
centimetres from a switching bridge. The same 20 nH per inch applies to both; a feedback trace
that wanders past the inductor produces a regulator that is stable on the bench and oscillates
when the motors run.
