+++
title = "Clearance, transition, interference — and how to read a fit like H7/g6"
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
related = ["corpus:mechanical/fits_tolerances/choosing-fits-bearing-dowel-press", "corpus:mechanical/fits_tolerances/process-tolerance-capability"]
further_reading = [
  { title = "Shigley's Mechanical Engineering Design", author = "Budynas, Nisbett", identifier = "" },
]
corpus_version = "0.1.0"
revised_in = "0.1.0"

[provenance]
source_class = "solus_authored"
source_title = "Solus engineering corpus"
source_publisher = "Solus"
source_license = "solus-proprietary"
accessed_at = 2026-09-06
checked_against = [
  { title = "ISO 286-1 — Geometrical product specifications (GPS) — ISO code system for tolerances on linear sizes — Part 1: Basis of tolerances, deviations and fits", author = "ISO", identifier = "ISO 286-1", url = "https://www.iso.org/" },
  { title = "ISO 286-2 — ISO code system for tolerances on linear sizes — Part 2: Tables of standard tolerance classes and limit deviations for holes and shafts", author = "ISO", identifier = "ISO 286-2", url = "https://www.iso.org/" },
]
+++

A fit describes what happens when a shaft goes into a hole of the same nominal size. There are only three outcomes:

- **Clearance fit** — the shaft is always smaller than the hole, so the parts slide or rotate. Bushings on a pin, a sliding cover, a rotating axle in a plain bore.
- **Interference fit** (press fit) — the shaft is always larger than the hole, so assembly needs force or heat and the parts are held by friction. A bearing pressed onto a shaft, a pin driven into a plate.
- **Transition fit** — the tolerance zones overlap, so a given pair may end up with a whisker of clearance or a whisker of interference. Used where you want location without play but still need to assemble by hand or with a light tap.

The ISO code system (ISO 286) encodes each side of the pair as a letter plus a number. The letter says *where* the tolerance zone sits relative to the nominal size (the fundamental deviation); the number says *how wide* the zone is (the IT grade — smaller number, tighter tolerance). Upper-case letters are holes, lower-case are shafts.

So `H7/g6` on a 20 mm nominal reads as:

| Part | Code | Meaning |
|------|------|---------|
| Hole | `H7` | Zone starts exactly at nominal and goes larger; grade 7 width |
| Shaft | `g6` | Zone sits just below nominal; grade 6 width (one grade tighter, because shafts are easier to hold tight than holes) |

Hole always at-or-above nominal, shaft always below nominal, so the result is a small guaranteed clearance: a close running fit.

The pattern to remember: with an `H` hole (the **hole-basis** system, which is the normal choice because standard reamers and drills make holes at nominal size), shaft letters early in the alphabet (`c`, `f`, `g`) give clearance, letters around `h`–`k`–`n` give transition, and later letters (`p`, `s`, `u`) give interference. The exact micrometre limits for each class and size range are tabulated in ISO 286-2; look them up rather than memorising them, and let your CAD tool's hole/shaft tolerance feature carry the class onto the drawing.
