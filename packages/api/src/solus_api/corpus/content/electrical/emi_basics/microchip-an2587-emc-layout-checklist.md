+++
title = "Microchip's EMC layout checklist: reference planes, pours, grounds, and TVS ratings"
kind = "procedure"
audience = "reference"
applicability = []
derivation = "summary"
confidence = 0.85
confidence_basis = "vendor_stated"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:electrical/emi_basics/motor-drive-noise-next-to-a-sensor", "corpus:electrical/grounding/ti-slyt499-agnd-dgnd-and-the-star-ground"]
further_reading = []
corpus_version = "0.2.0"
revised_in = "0.2.0"

[provenance]
source_class = "vendor_documentation"
source_title = "AN2587 EMI, EMC, EFT, and ESD Circuit Design Consideration for 32-bit Microcontrollers (DS00002587A)"
source_publisher = "Microchip Technology"
source_url = "https://ww1.microchip.com/downloads/aemDocuments/documents/OTH/ApplicationNotes/ApplicationNotes/00002587A.pdf"
source_locator = "2017, §2, §6.1, §7.1 (pp. 6–9, 24, 27–28)"
source_license = "vendor-terms"
accessed_at = 2026-09-06
attribution = "Microchip Technology, AN2587, 2017, §2, §6.1, §7.1 (pp. 6–9, 24, 27–28)"
+++

Microchip's AN2587 is a long application note on getting a microcontroller board through
immunity and emissions testing. Its layout section is a checklist; the parts that transfer to a
robot controller are restated here in Solus's words.

The framing the note gives: a large share of products fail their first EMC lab visit, test fees
are significant, and a board turn costs more than a layout review. Near-field scanners exist for
finding hot spots, but the cheaper tool is the checklist below applied before the first
prototype.

Layout practices the note lists first:

1. Route differential and high-speed traces first, on the top layer, adjacent to a ground plane
   layer, holding their impedance.
2. Give every clock and fast signal an unbroken reference plane beneath it: no gaps, no voids,
   no plane splits crossed. A signal that jumps a split has no return path and radiates.
3. Pour unused signal-layer area with signal ground, stitched to the plane.
4. Where analog and digital grounds are kept separate, join them at one place only, at the power
   ground nearest the input regulator, so return currents from the digital side cannot circulate
   through the analog copper.

Transient protection the note covers: an ESD or fast-transient event shifts the ground reference
and can trigger latch-up paths inside a device, so the protection has to be at the entry point.
It recommends TVS diodes as the primary suppressor for both ESD and electrical fast transients
because of their response time, with ferrite beads and filter capacitors as the second layer,
and it warns that a TVS datasheet claiming a compliance level without stating the test conditions
is not a specification. As a vendor-stated sizing guide, it puts a TVS for the higher immunity
levels of IEC 61000-4-2 in the 250–400 W peak-pulse-power range.

Why a robot cares: a controller sitting beside brushless drives and long unshielded sensor cables
lives in an EFT environment every time a motor commutates. Ground splits crossed by SPI clocks,
sensor inputs with no TVS, and voids under a UART to the companion computer are the three
faults this checklist catches most often.
