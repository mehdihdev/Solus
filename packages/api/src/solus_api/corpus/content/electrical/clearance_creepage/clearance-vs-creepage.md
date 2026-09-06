+++
title = "Clearance is through air, creepage is along a surface, and they fail differently"
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
related = ["corpus:electrical/clearance_creepage/pollution-degree-slots-and-coatings", "corpus:electrical/clearance_creepage/why-48v-still-matters"]
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
  { title = "IPC-2221 Generic Standard on Printed Board Design", author = "IPC", identifier = "IPC-2221", url = "https://www.ipc.org/" },
]
+++

Two conductors at different potentials need to be kept apart in two distinct ways, and the words are not interchangeable.

Clearance is the shortest distance between them through the air. It fails by breakdown: the air ionises and an arc jumps the gap. What drives it is the peak voltage that can appear across the gap, including transients from switching, motor commutation, and ESD, not the nominal rail. Air pressure matters, so altitude reduces the margin, and a gap that is fine at sea level is not the same gap at 3,000 m.

Creepage is the shortest distance between them along the surface of an insulator, such as the PCB laminate or a connector body. It fails by tracking: moisture and contamination on the surface let a tiny leakage current flow, which locally heats and carbonises the material, and the carbon track grows until it bridges the gap. This is slow, sometimes months, and depends on the working voltage (usually RMS), how dirty and humid the environment is, and how resistant the insulating material is to tracking, expressed by its comparative tracking index.

Because the mechanisms differ, the required creepage is usually larger than the required clearance for the same voltage, and creepage can never be less than clearance. IEC 60664-1 is the insulation-coordination standard that defines these terms and organises the requirements by working voltage, pollution degree, material group, and overvoltage category. IPC-2221 gives conductor spacing for printed boards by voltage and by whether the conductors are internal, external bare, or external coated. Use those documents for the numbers; the principle to carry is that "spacing" on a board is two separate questions, and both must be checked against the worst-case voltage rather than the nominal one.
