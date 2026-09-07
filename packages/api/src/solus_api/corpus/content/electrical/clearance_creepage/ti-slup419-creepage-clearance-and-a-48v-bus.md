+++
title = "Creepage versus clearance, what sets each, and where a 48 V bus sits"
kind = "principle"
audience = "fundamentals"
applicability = []
derivation = "summary"
confidence = 0.85
confidence_basis = "vendor_stated"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:electrical/clearance_creepage/clearance-vs-creepage", "corpus:electrical/clearance_creepage/ti-sluaar5-iec-60664-method-for-a-drive-board", "corpus:electrical/clearance_creepage/why-48v-still-matters"]
further_reading = []
corpus_version = "0.2.0"
revised_in = "0.2.0"

[provenance]
source_class = "vendor_documentation"
source_title = "Demystifying Clearance and Creepage Distance for High-Voltage End Equipment (SLUP419, Power Supply Design Seminar SEM2600 Topic 2)"
source_publisher = "Texas Instruments"
source_url = "https://www.ti.com/lit/pdf/slup419"
source_locator = "March 2024, pp. 2–6"
source_license = "vendor-terms"
accessed_at = 2026-09-06
attribution = "Texas Instruments, SLUP419, March 2024, pp. 2–6"
+++

TI's 2024 seminar paper on clearance and creepage is the clearest short treatment of what the
two distances are for. Restated:

Creepage is the shortest path between two conductors along the surface of the insulator between
them. It exists to stop tracking, the slow growth of a conductive path across a surface, so it is
dimensioned for the long-term working voltage (the RMS value) and is governed by pollution
(humidity, dust, condensation) and by the insulator's comparative tracking index, or CTI.
Clearance is the shortest path through air. It exists to stop arcing during a transient, so it is
dimensioned for the peak voltage including surges, and is governed by air pressure and
pollution; above 2,000 m altitude a multiplying factor applies. The two have no physical
relationship except one rule: creepage can never be less than clearance.

The insulator matters. Materials are grouped by CTI, and the paper notes that most FR4 used in
PCB fabrication falls in material group IIIa, the group that demands the largest creepage for a
given voltage. Slots cut in the board lengthen the surface path and so raise creepage without
changing clearance; the shortest creepage on a package can run around the side of the body rather
than across the top, and depopulating pins raises both distances.

Where a robot's 48 V bus sits. The paper groups circuits into energy-source classes: up to 60 V is
ES1, safe to touch and needing no isolation from a user; 60–120 V is ES2 and needs basic
isolation; above 120 V needs reinforced isolation. A 48 V DC motor bus is therefore ES1 (SELV in
older IEC 60950-1 terms), and spacing on the bus itself is a functional-insulation question: it
must not arc or track in service, but it is not a shock barrier. The isolation grade only rises
where that bus meets something else, for example an AC/DC rectifier with a 48 V output needs
basic isolation from its earthed primary, or reinforced if the output is unearthed.

What this does not tell you is the number. The distance for a given working voltage, pollution
degree, and material group comes from the tables of the applicable standard (IEC 60664-1 for
insulation coordination, or the end-equipment standard), which the paper walks through as a
method; the companion chunk on the IEC 60664 procedure gives the steps, and the value itself
comes from the standard, not from this corpus.
