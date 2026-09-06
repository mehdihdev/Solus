+++
title = "What moves the spacing numbers: pollution degree, voltage class, slots, and coatings"
kind = "rule_of_thumb"
audience = "reference"
applicability = []
derivation = "solus_original"
confidence = 0.85
confidence_basis = "standard_derived"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:electrical/clearance_creepage/clearance-vs-creepage"]
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
  { title = "IEC 60664-1 Insulation coordination for equipment within low-voltage supply systems — Principles, requirements and tests", author = "IEC", identifier = "IEC 60664-1", url = "https://www.iec.ch/" },
  { title = "IEC 60664-3 Insulation coordination — Use of coating, potting or moulding for protection against pollution", author = "IEC", identifier = "IEC 60664-3", url = "https://www.iec.ch/" },
  { title = "IPC-2221 Generic Standard on Printed Board Design", author = "IPC", identifier = "IPC-2221", url = "https://www.ipc.org/" },
]
+++

The spacing tables in IEC 60664-1 and IPC-2221 are indexed by a handful of inputs. Knowing what each one does lets you predict which way the number will move before you open the standard.

Working voltage. Clearance is driven by the peak voltage including transients; creepage by the steady working voltage. A 48 V nominal bus with a 60 V charge and regenerative spikes is assessed at those values, not at 48 V.

Pollution degree. This describes the environment the surface lives in: from sealed and clean, through ordinary indoor air with occasional condensation, to conductive dust or persistent moisture. Each step up lengthens the required creepage substantially. An outdoor or workshop robot that breathes unfiltered air is not the clean case. Encapsulation or a sealed enclosure can justify a lower degree.

Material group. Laminates with a higher comparative tracking index tolerate shorter creepage. Common FR-4 sits in a middle group; check the laminate datasheet rather than assuming.

Altitude. Clearance requirements in IEC 60664-1 are stated for operation up to 2,000 m and require a correction factor above that.

Slots. A routed slot cut through the board between two conductors forces the surface path to go around it, which increases creepage without moving parts apart; it does little for clearance unless it also widens the air gap. A shallow groove counts only if it is wide enough, and the standard sets that minimum.

Coatings. Conformal coating or potting that qualifies under IEC 60664-3 lets the covered region be treated as protected, which allows reduced spacing. Ordinary solder mask does not qualify by itself; IPC-2221 distinguishes coated from uncoated external conductors for exactly this reason, and the coating has to be applied and inspected as a process, not assumed.

Rule of thumb: decide the environment honestly first, then the worst-case voltage, then read the tables. The limits of this rule are the standards themselves; consult them for every value.
