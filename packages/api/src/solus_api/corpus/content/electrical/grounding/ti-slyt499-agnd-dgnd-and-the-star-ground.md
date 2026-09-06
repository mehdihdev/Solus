+++
title = "AGND and DGND pins, the star ground, and whether to split the plane"
kind = "principle"
audience = "fundamentals"
applicability = []
derivation = "summary"
confidence = 0.9
confidence_basis = "vendor_stated"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:electrical/grounding/star-vs-plane-and-mixed-signal", "corpus:electrical/grounding/where-return-current-flows"]
further_reading = []
corpus_version = "0.2.0"
revised_in = "0.2.0"

[provenance]
source_class = "vendor_documentation"
source_title = "Grounding in mixed-signal systems demystified, Part 1 (SLYT499, Analog Applications Journal 1Q 2013)"
source_publisher = "Texas Instruments"
source_url = "https://www.ti.com/lit/an/slyt499/slyt499.pdf"
source_locator = "1Q 2013, pp. 5–8"
source_license = "vendor-terms"
accessed_at = 2026-09-06
attribution = "Texas Instruments, SLYT499, 1Q 2013, pp. 5–8"
+++

TI's Analog Applications Journal article on mixed-signal grounding clears up the two things
that confuse everyone who wires their first ADC. In Solus's words:

The star ground is a way of thinking, not a layout. It means every voltage in the system is
referred to one point in the ground network, so measurements are made against something
definite rather than wherever a probe clips. Drawn literally, with every signal routed to one
node, it is impractical: power supplies add their own return paths, and their currents in
shared ground copper corrupt signals. The practical form of the idea is a plane.

A ground plane is a low-impedance return. A bus wire used as ground has an impedance at the
frequencies of logic edges that turns return current into an error voltage; a continuous copper
layer has the lowest resistance and inductance a conductor can have on a board. The plane is
the return path for the decoupling currents of fast logic, it reduces both emissions and
susceptibility by shielding, and it is what makes controlled-impedance traces possible.

AGND and DGND describe the inside of the chip, not your board. A mixed-signal converter keeps
its analog and digital grounds separate internally to stop digital currents coupling into the
analog section through the substrate and package. The pin names say that. They do not
instruct you to build two ground systems; the datasheet's usual advice is to tie AGND and DGND
together at the device, with the shortest possible leads. Extra impedance in the DGND
connection lets more digital noise couple across the chip's stray capacitance.

If you do separate analog and digital planes, remember the converter is analog: its AGND and
DGND both go to the analog plane. Tied to the digital plane, the single-ended analog input gets
digital noise summed into it. The small digital return current this puts into the quiet plane
is acceptable, and is minimised by not letting the converter's outputs drive a large fan-out.

Whether to split at all depends on the converter's digital current. Low-current converters are
simple; high-current ones (heavy digital filtering, wide fast output buses) need the partitioning
the article's Part 2 describes. The rule that survives either way: a return path exists whether
or not you drew it, and the plane under a signal is where its return current wants to flow.
