+++
title = "Tolerance stack-up: worst case versus root-sum-square"
kind = "procedure"
audience = "fundamentals"
applicability = []
derivation = "solus_original"
confidence = 0.85
confidence_basis = "consensus"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:mechanical/fits_tolerances/fit-classes-and-reading-h7-g6", "corpus:mechanical/gdt/datums-and-feature-control-frames"]
further_reading = [
  { title = "Mechanical Tolerance Stackup and Analysis", author = "Fischer", identifier = "" },
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
  { title = "ASME Y14.5 — Dimensioning and Tolerancing", author = "ASME", identifier = "ASME Y14.5", url = "https://www.asme.org/" },
  { title = "ISO 286-1 — ISO code system for tolerances on linear sizes — Part 1", author = "ISO", identifier = "ISO 286-1", url = "https://www.iso.org/" },
]
+++

A stack-up asks: given the tolerance on each part in a chain, how far can the resulting gap (or overlap) vary? Do it whenever several toleranced dimensions add up to something you care about — a sensor-to-target distance, a belt centre distance, whether a lid still closes.

**Procedure**

1. Draw the loop. Start at one face of the gap and walk through every part and contact surface to the other face, writing each dimension with a sign (+ in one direction, − in the other). Include the fit clearances of any pins or bearings in the loop.
2. Nominal gap = signed sum of the nominals. If this is not what you wanted, fix the design before touching tolerances.
3. Convert every dimension to symmetric form, `nominal ± t`.
4. **Worst case**: total variation is the plain sum of the `t` values. If everything is simultaneously at its bad limit, this is what you get. Nothing is assumed about the manufacturing process.
5. **Root-sum-square (RSS)**: total variation is the square root of the sum of the squared `t` values:

```
T_rss = sqrt(t1^2 + t2^2 + ... + tn^2)
```

RSS is smaller because independent random errors rarely all line up. It is only valid when each dimension is produced by a process that is independent of the others and roughly centred on nominal, and when there are enough contributors (a handful or more) for the statistics to mean anything.

**Which to use**

- Worst case for anything safety-related, anything with two or three contributors, and any dimension a supplier can legitimately deliver at the limit (a purchased part at its catalogue extreme is not a random sample).
- RSS when a worst-case analysis fails by a margin that would force expensive tolerances and you can accept that a small fraction of assemblies will miss. State the assumption on the drawing or in the design note.
- If neither closes the gap, change the design: add an adjustment (slot, shim, eccentric), datum the critical features to each other so fewer parts sit in the loop, or turn the stack into a single machined feature.

A stack-up that ignores fit clearances, or that uses linear tolerances where the drawing actually applies a geometric position or profile control, will be wrong in a way that looks precise.
