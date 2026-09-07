+++
title = "Position versus profile, and the bonus tolerance from a material-condition modifier"
kind = "rule_of_thumb"
audience = "reference"
applicability = []
derivation = "solus_original"
confidence = 0.8
confidence_basis = "standard_derived"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:mechanical/gdt/datums-and-feature-control-frames", "corpus:mechanical/fits_tolerances/fit-classes-and-reading-h7-g6"]
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
  { title = "ASME Y14.5 — Dimensioning and Tolerancing", author = "ASME", identifier = "ASME Y14.5", url = "https://www.asme.org/" },
  { title = "ISO 2692 — Geometrical product specifications (GPS) — Geometrical tolerancing — Maximum material requirement (MMR), least material requirement (LMR) and reciprocity requirement (RPR)", author = "ISO", identifier = "ISO 2692", url = "https://www.iso.org/" },
]
+++

**When to use position.** Position controls *features of size* — holes, pins, slots, bosses — things that have an axis or centre plane. Use it for every hole pattern that mates with another part: bolt holes, dowel holes, bearing bores, connector cut-outs that must line up with a PCB. The tolerance zone is a cylinder (or a pair of planes for a slot) centred on the true position defined from the datums, and the feature's axis must lie inside it.

**When to use profile.** Profile of a surface controls the shape of *any* surface, curved or flat, and — if datums are referenced — its location too. Use it for a housing's outer surfaces, a cam, a sheet-metal outline, and for parts where a ± dimension to every face would be unreadable. A single profile tolerance applied "all over" with a general note is the modern way to tolerance a complex part, leaving position controls for the mating holes.

Rule of thumb: **holes and pins get position; everything else gets profile.** Plain ± tolerances remain for sizes (a hole's diameter, a plate's thickness) and for features whose location genuinely does not matter.

**Material-condition modifiers and bonus tolerance.** A position tolerance on a hole can be marked with the maximum-material-condition modifier (a circled M). Maximum material condition (MMC) is the hole at its smallest allowed diameter — the state with the most metal left. The stated position tolerance applies at MMC; as the actual hole is made *larger* than MMC, the position tolerance grows by exactly the same amount. That extra allowance is the **bonus tolerance**. The logic is functional: a bigger hole can sit further off-centre and still clear the pin. The least-material modifier (circled L) does the mirror image, protecting a minimum wall or edge distance. ISO 2692 defines the same idea as the maximum and least material requirements.

Practical consequences:

- Use the MMC modifier on clearance holes for fasteners and on pins that must fit into holes; it lets the shop use the size tolerance to relax position and lowers cost without changing whether the parts assemble.
- Do not use MMC on a feature whose location itself is functional regardless of size — a bearing bore's axis, a sensor's optical axis. There the modifier gives away accuracy you needed. Use the "regardless of feature size" default (no modifier).
- A stack-up must use the same modifier the drawing grants: assuming a bonus that is not there underestimates the worst case.
