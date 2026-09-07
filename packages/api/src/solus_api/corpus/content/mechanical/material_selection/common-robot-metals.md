+++
title = "6061, 7075, 304, 316, 4140: where each is the wrong choice"
kind = "rule_of_thumb"
audience = "reference"
applicability = []
derivation = "solus_original"
confidence = 0.8
confidence_basis = "consensus"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:mechanical/material_selection/stiffness-vs-strength", "corpus:mechanical/material_selection/galling-and-galvanic-pairs", "corpus:mechanical/material_selection/anodise-vs-plate"]
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
  { title = "MIL-HDBK-5J — Metallic Materials and Elements for Aerospace Vehicle Structures", author = "US Department of Defense", identifier = "MIL-HDBK-5J", url = "https://quicksearch.dla.mil/" },
  { title = "ASTM A240 — Standard Specification for Chromium and Chromium-Nickel Stainless Steel Plate, Sheet, and Strip", author = "ASTM International", identifier = "ASTM A240", url = "https://www.astm.org/" },
  { title = "ASTM B221 — Standard Specification for Aluminum and Aluminum-Alloy Extruded Bars, Rods, Wire, Profiles, and Tubes", author = "ASTM International", identifier = "ASTM B221", url = "https://www.astm.org/" },
]
+++

The five metals a robotics team meets most, described by when *not* to use them. Properties are typical for the common tempers; take design values from a certified source.

| Alloy | Default use | Wrong when… |
|-------|-------------|-------------|
| **6061-T6** aluminium | Machined structure, brackets, plates. Cheap, machines beautifully, anodises well, weldable (loses temper at the weld). | You need strength beyond roughly 270 MPa yield; you need it to survive a hard impact without denting; the part is a thread-bearing housing for repeated fastener cycles (use inserts). |
| **7075-T6** aluminium | High-strength, weight-critical links and parts. Roughly 500 MPa yield at the same stiffness and density as 6061. | You wanted stiffness (identical to 6061); the part is welded (7075 is not weldable in practice); it lives outdoors or in salt without coating (worse corrosion and stress-corrosion behaviour than 6061); cost matters. |
| **304** stainless | Fasteners, shafts in wet environments, food or lab contact. | You need high strength (roughly 200–250 MPa yield annealed, softer than a plated 8.8 steel bolt); stainless-on-stainless sliding or threading (galls); it is chosen "because stainless is strong" — it is corrosion-resistant, not strong. |
| **316** stainless | Same as 304 but with chlorides: seawater, pool chemistry, de-icing salt. | The environment is dry indoor and you are paying extra for nothing; you need magnetic response (304 and 316 are essentially non-magnetic when annealed). |
| **4140** alloy steel | Shafts, gears, pins, high-load pivots — heat-treatable to high strength and hardness, about three times aluminium's stiffness. | Weight matters and the section is not stiffness-limited; it will be unfinished in a damp environment (rusts readily — plate, black-oxide and oil, or design for it); you need it welded after heat treatment. |

Two cross-cutting rules:

- **Do not match strength to a shape sized by stiffness.** A link that is sized so it does not flex is usually far below yield in any of these metals; the cheapest one that machines well is correct.
- **Every dissimilar-metal joint that may get wet is a galvanic pair**: stainless fasteners in aluminium, aluminium plates on steel frames. Either isolate it, coat it, or accept and inspect it. Details in the galling-and-galvanic chunk.

Where a printed or moulded plastic (POM, nylon, PETG) can do the job, it is often lighter and cheaper than any of these; see the plastics chunk for their limits.
