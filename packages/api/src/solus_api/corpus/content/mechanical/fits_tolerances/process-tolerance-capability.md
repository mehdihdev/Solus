+++
title = "Asking a process for a tolerance it cannot hold"
kind = "pitfall"
audience = "reference"
applicability = []
derivation = "solus_original"
confidence = 0.7
confidence_basis = "rule_of_thumb"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:mechanical/fits_tolerances/fit-classes-and-reading-h7-g6", "corpus:mechanical/machining_constraints/drill-vs-ream", "corpus:mechanical/machining_constraints/fdm-orientation-overhangs-bridging"]
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
  { title = "ISO 2768-1 — General tolerances — Part 1: Tolerances for linear and angular dimensions without individual tolerance indications", author = "ISO", identifier = "ISO 2768-1", url = "https://www.iso.org/" },
  { title = "ISO/ASTM 52910 — Additive manufacturing — Design — Requirements, guidelines and recommendations", author = "ISO/ASTM", identifier = "ISO/ASTM 52910", url = "https://www.iso.org/" },
]
+++

The failure: a drawing carries `±0.01 mm` on a feature because the CAD default was tight, or a printed bracket is modelled with a 6.00 mm hole for a 6 mm shaft, and the part either arrives late and expensive or does not fit at all. Tolerance is a property of the process, not a wish on a drawing.

Working defaults, each to be replaced by your shop's or printer's measured capability:

| Process | What it holds without special effort | What costs extra |
|---------|--------------------------------------|------------------|
| CNC milling / turning, job shop | roughly ±0.1 mm on ordinary features (the "medium" general-tolerance class of ISO 2768 is what most shops assume when the drawing says nothing) | ±0.025 mm and tighter; IT7-class holes need reaming or boring, not drilling |
| Laser-cut / bent sheet metal | ±0.1–0.2 mm on cut profiles; bends noticeably worse, and hole-to-bend distances worst of all | any hole that must line up across a bend |
| FDM printing | ±0.2–0.5 mm, plus holes that come out **smaller** than modelled and outer dimensions slightly larger | anything under ±0.1 mm — plan to post-machine, ream, or use an insert |
| SLA / resin printing | better than FDM, but parts shrink and warp during cure | thin flat features, large flat faces |

The rules that follow from this:

- Put a general-tolerance note on the drawing (ISO 2768 class, or an ASME equivalent) and tolerance individually only the features that matter. Every tight tolerance is a line item.
- Never specify an ISO fit class (`H7`, `g6`) on a printed part as if it will arrive that way. Model the hole undersize, then drill or ream to size, or design in a bushing or heat-set insert.
- For FDM, calibrate: print a test piece with a range of hole sizes and measure. The offset is specific to the printer, material, and slicer settings, and it is what your design should compensate for.
- When a fit between a printed part and a machined part matters, put the precision on the machined side and give the printed side generous clearance plus a way to adjust.

Confidence here is a rule of thumb: the numbers are typical of what small shops and desktop printers deliver, not guarantees. A quoted process capability from the actual supplier beats every row above.
