+++
title = "How to derive board spacing from IEC 60664 for a motor-drive PCB"
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
related = ["corpus:electrical/clearance_creepage/ti-slup419-creepage-clearance-and-a-48v-bus", "corpus:electrical/clearance_creepage/pollution-degree-slots-and-coatings"]
further_reading = []
corpus_version = "0.2.0"
revised_in = "0.2.0"

[provenance]
source_class = "vendor_documentation"
source_title = "Circuit Board Insulation Design According to IEC60664 for Motor Drive Application (SLUAAR5, technical white paper)"
source_publisher = "Texas Instruments"
source_url = "https://www.ti.com/lit/pdf/sluaar5"
source_locator = "August 2023, §1–2"
source_license = "vendor-terms"
accessed_at = 2026-09-06
attribution = "Texas Instruments, SLUAAR5, August 2023, §1–2"
+++

TI's white paper SLUAAR5 turns IEC 60664-1 into a procedure for a drive board. The steps, in
Solus's words, with the vocabulary the standard uses:

1. Split the board into voltage blocks: the DC bus and power stage, the gate-drive side, the
   control and communication side, anything touching the mains. Insulation is specified between
   blocks, not for the board as a whole.
2. Decide the insulation type needed between each pair of blocks: functional (only needed for
   the circuit to work, no shock protection), basic (one layer of shock protection), or
   reinforced (equivalent to double). The paper's motor-drive example needs reinforced insulation
   between the high-voltage power side and anything a person can touch, and functional insulation
   within the low-voltage side.
3. Establish the overvoltage category (how exposed the block is to mains transients) and the
   pollution degree of the micro-environment around the insulation (the paper tabulates the four
   degrees; a sealed enclosure and a dusty workshop are different degrees).
4. Find the working voltage between the blocks. Clearance uses the peak, including transients,
   because breakdown through air is fast. Creepage uses the RMS or DC value, because tracking
   along a surface is slow and driven by the steady voltage.
5. Read clearance and creepage from the standard's tables for those inputs and the insulator's
   material group (CTI). Take the larger of the two as the spacing you enforce, and enter it as a
   design-rule constraint in the layout tool so it is checked, not remembered.
6. If a package pitch cannot meet the creepage, a groove or slot in the board lengthens the
   surface path; it does not change clearance. Above 2,000 m an altitude factor scales clearance.

Two definitions worth keeping: extra-low voltage in this framework is anything not exceeding
50 V AC RMS or 120 V DC, so a 48 V DC robot bus is ELV; and the decisive voltage class (from
IEC 61800-5-1) is what decides the shock-protection measures for a drive.

The values come from the standard's tables, which the paper reproduces for its example and this
corpus does not. What the corpus can say is the procedure and the inputs; the number for your
board is read from IEC 60664-1 (or your product's equipment standard) with your pollution
degree and material group.
