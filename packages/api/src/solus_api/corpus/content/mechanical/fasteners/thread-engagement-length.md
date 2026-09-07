+++
title = "Thread engagement length in steel, aluminium, and plastic"
kind = "rule_of_thumb"
audience = "reference"
applicability = []
derivation = "solus_original"
confidence = 0.75
confidence_basis = "rule_of_thumb"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:mechanical/fasteners/preload-not-torque", "corpus:mechanical/fasteners/heat-set-inserts-in-printed-parts", "corpus:mechanical/material_selection/galling-and-galvanic-pairs"]
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
  { title = "Fastener Design Manual (NASA Reference Publication 1228)", author = "Barrett, NASA Lewis Research Center", identifier = "NASA-RP-1228", url = "https://ntrs.nasa.gov/" },
  { title = "ISO 898-1 — Mechanical properties of fasteners made of carbon steel and alloy steel — Part 1", author = "ISO", identifier = "ISO 898-1", url = "https://www.iso.org/" },
]
+++

A tapped hole fails by the internal threads shearing out, and the shear area grows with engaged length. The bolt, meanwhile, fails in tension at its stress area, which is fixed. The design goal is that the **bolt breaks before the threads strip**, because a broken bolt is a visible, replaceable failure and stripped threads in a machined housing are a scrapped part. How much engagement that takes depends on how much weaker the tapped material is than the bolt.

Defaults, expressed as a multiple of the nominal thread diameter `d`, for a standard-strength steel bolt (property class 8.8 or similar):

| Tapped material | Minimum engagement | Why |
|-----------------|--------------------|-----|
| Steel, similar strength to the bolt | ≈ 1 × d | Thread and bolt strength are matched |
| Aluminium alloys (6061-T6 and similar) | 1.5 – 2 × d | Aluminium shear strength is far below the bolt's |
| Cast alloys, brass, soft steels | ≈ 2 × d | Lower shear strength and less consistent |
| Engineering plastics (POM, nylon, glass-filled) | 2 – 2.5 × d | Very low shear strength; creep under preload |
| FDM-printed plastics, tapped directly | Do not rely on it | Layer lines, voids, and creep — use a heat-set or threaded insert instead |

Read the table as "the threads in this material need this much length to out-carry the bolt". More engagement than about 2.5 × d buys little, because the load is carried mostly by the first few threads anyway.

Limits and refinements:

- These are for coarse threads. Fine threads have shallower thread depth and want more engagement in soft materials.
- A high-strength bolt (10.9, 12.9) into aluminium will strip the aluminium before the bolt yields regardless of engagement in the 1–2 × d range. Either accept that the aluminium threads are the weak link and size preload to them, or use a threaded insert (helical or solid) that spreads the load over a larger, coarser external thread.
- Counted engagement excludes the chamfer and the incomplete threads at the bottom of a blind hole; add drill depth accordingly, and add clearance for the tap's lead if the hole is blind.
- Stainless screws into aluminium in a damp or outdoor environment are also a galvanic pair; the corrosion products swell and can strip the threads over time. Use an insert or a plated steel screw with a coating designed for aluminium contact.
