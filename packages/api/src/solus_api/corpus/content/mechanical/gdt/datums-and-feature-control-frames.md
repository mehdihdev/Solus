+++
title = "GD&T in one page: datums, the feature control frame, and what each control does"
kind = "principle"
audience = "fundamentals"
applicability = []
derivation = "solus_original"
confidence = 0.85
confidence_basis = "standard_derived"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:mechanical/gdt/position-vs-profile-and-bonus-tolerance", "corpus:mechanical/fits_tolerances/stack-up-worst-case-vs-rss"]
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
  { title = "ISO 1101 — Geometrical product specifications (GPS) — Geometrical tolerancing — Tolerances of form, orientation, location and run-out", author = "ISO", identifier = "ISO 1101", url = "https://www.iso.org/" },
  { title = "ISO 5459 — Geometrical product specifications (GPS) — Geometrical tolerancing — Datums and datum systems", author = "ISO", identifier = "ISO 5459", url = "https://www.iso.org/" },
]
+++

Plus-or-minus dimensions say how big a feature is. They say very little about *where* it is or *what shape* it is, and a drawing built only from them leaves the inspector to guess which surface to measure from. Geometric dimensioning and tolerancing (GD&T, per ASME Y14.5 in North America and the ISO 1101 family elsewhere) fixes that with two ideas.

**Datums.** A datum is a theoretically perfect plane, axis, or point that the part's real, imperfect surface is taken to represent. Labelling three mutually perpendicular faces `A`, `B`, `C` establishes a **datum reference frame** — the coordinate system every other feature is located in, in that order of priority. Pick datums the way the part is actually fixtured and the way it mates: the face that bolts to the frame is `A`, the pin holes that locate it are `B`, and so on. A datum chosen for drawing convenience rather than function is the most common GD&T mistake.

**The feature control frame** is the rectangular box that applies a control to a feature. Reading left to right: the *symbol* for the control; the *tolerance zone* (a diameter symbol if the zone is cylindrical, then the size, then any material-condition modifier); then the *datums* referenced, in order. "Position, Ø0.2, at maximum material condition, relative to A then B then C" is a complete sentence about where a hole may be.

**What the controls do**, grouped by what they constrain:

| Group | Controls | Constrains | Needs a datum? |
|-------|----------|------------|----------------|
| Form | flatness, straightness, circularity, cylindricity | the feature's own shape | no |
| Orientation | perpendicularity, parallelism, angularity | tilt relative to a datum | yes |
| Location | position, concentricity/coaxiality, symmetry | where the feature's axis or centre plane is | yes |
| Profile | profile of a line, profile of a surface | shape *and* (with datums) location of any surface, curved or not | optional |
| Run-out | circular, total | wobble of a rotating surface about an axis | yes (the axis) |

The standards define each zone precisely; the table is the map, not the definitions.

Why a robotics team should care even at prototype scale: a bearing bore located by position to the mounting datums, rather than by a ± dimension from a random edge, is what makes two housings interchangeable and a stack-up calculable. Anyone reading a mechanical drawing can decode most of it from the frame: symbol, zone, datums.
