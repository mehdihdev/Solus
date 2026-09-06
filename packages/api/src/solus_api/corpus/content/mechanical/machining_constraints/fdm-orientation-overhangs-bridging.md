+++
title = "Designing for FDM: print orientation sets strength, overhangs, and accuracy"
kind = "procedure"
audience = "fundamentals"
applicability = [{ key = "process", value = "fdm" }]
derivation = "solus_original"
confidence = 0.8
confidence_basis = "consensus"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:mechanical/material_selection/printed-plastics-temperature-limits", "corpus:mechanical/fasteners/heat-set-inserts-in-printed-parts", "corpus:mechanical/fits_tolerances/process-tolerance-capability"]
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
  { title = "ISO/ASTM 52910 — Additive manufacturing — Design — Requirements, guidelines and recommendations", author = "ISO/ASTM", identifier = "ISO/ASTM 52910", url = "https://www.iso.org/" },
  { title = "ISO/ASTM 52921 — Standard terminology for additive manufacturing — Coordinate systems and test methodologies", author = "ISO/ASTM", identifier = "ISO/ASTM 52921", url = "https://www.iso.org/" },
]
+++

An FDM part is a stack of extruded layers welded to each other by heat. The weld between layers is always weaker than the continuous plastic within a layer, so the part is **anisotropic**: strong along the layer plane, weak across it (the build Z direction). Every design decision for a printed part starts from choosing which way the layers will run.

**Procedure**

1. **Find the load path first.** Identify the tensile and bending stresses in the part. Orient the part so those stresses run *along* the layers, never across them. A hook, a snap-fit tab, a cantilevered arm, a lug with a bolt through it: each should be printed so its cross-section is built up layer by layer along its length, not so that a layer line cuts across it. A part that breaks cleanly along a flat plane broke at a layer line: wrong orientation.
2. **Then check overhangs.** Each layer must sit on something. Walls leaning outward up to roughly 45° from vertical print acceptably on most machines; beyond that the outer edge of each layer hangs in air and droops, and past about 60° you need support material. Supports cost time and leave a rough surface. Chamfer instead of fillet on undersides (a 45° chamfer prints; a fillet's tangent bottom does not).
3. **Bridging.** A flat span between two supported walls prints in the air for a few tens of millimetres on a tuned printer, with sag underneath. Longer, or anything that must be flat, needs support or a chamfered roof.
4. **Holes.** Horizontal-axis holes print as stacked polygons with a sagging top and are the least round feature you can make; orient precision holes vertically. All holes come out undersize: model them larger, or print undersize and drill.
5. **Walls.** Make wall thickness a whole number of extrusion widths (multiples of roughly 0.4–0.5 mm for a standard nozzle) so the slicer fills it solidly; a 1.0 mm wall from a 0.4 mm nozzle is two perimeters and a gap.
6. **Warping.** Large flat footprints and sharp bed-contact corners pull up, worst in high-shrink materials such as ABS. Round those corners and add a brim.
7. **Say which way it goes.** Record the intended build orientation with the model (ISO/ASTM 52921 gives the coordinate conventions) so whoever prints it does not lie a part flat that was designed to stand up.

Orientation, layer height, temperature, and infill together change strength by a factor of two or more; a printed structural part is only as characterised as the settings it was printed with.
