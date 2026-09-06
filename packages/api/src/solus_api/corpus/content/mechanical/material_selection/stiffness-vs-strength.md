+++
title = "Stiffness is not strength: why a 7075 part flexes exactly as much as a 6061 one"
kind = "principle"
audience = "fundamentals"
applicability = []
derivation = "solus_original"
confidence = 0.9
confidence_basis = "government_published"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:mechanical/material_selection/common-robot-metals", "corpus:mechanical/material_selection/printed-plastics-temperature-limits"]
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
]
+++

Two different material properties answer two different questions, and robot designers mix them up constantly.

**Strength** (yield strength, tensile strength) answers: *at what stress does the part permanently deform or break?* It is set by alloy and heat treatment. **Stiffness** (Young's modulus, `E`) answers: *how much does the part deflect under a load it survives?* It is set almost entirely by the base metal and barely changes with alloy or temper.

The consequence: switching an aluminium bracket from 6061-T6 to 7075-T6 nearly doubles its yield strength (roughly 270 MPa to roughly 500 MPa in the common tempers) but leaves its modulus at about 70 GPa. An arm link that sags too much, a camera mount that vibrates, a gantry that flexes under a cutting load — none of those improve with the stronger alloy. They improve with geometry (a deeper section, a closed tube, a rib), or with a stiffer base metal. Steel's modulus is about 200 GPa, roughly three times aluminium's, for roughly three times the density (about 7.85 versus 2.7 g/cm³), so a steel and an aluminium beam of the same *mass* and the same shape family have similar stiffness — aluminium simply gets there with a bigger section.

A useful check when a part is "not strong enough":

- If it broke or bent permanently → a strength problem. Alloy, heat treatment, section area, stress concentrations at corners and holes.
- If it deflected, resonated, or lost accuracy → a stiffness problem. Second moment of area (depth cubed for a beam), modulus, joint compliance. Changing to a stronger alloy of the same metal does nothing.
- If it cracked after many cycles → a fatigue problem, which is a strength problem with a much lower allowable and a strong dependence on surface finish and notches.

Bending deflection scales with `1 / (E · I)`, and `I` grows with the cube of section depth, so doubling a beam's depth cuts deflection by about a factor of eight — far more than any material swap. Design for stiffness with shape; buy strength with alloy only where a stiff-enough part still yields.

For design values, use a published allowables source (MIL-HDBK-5 and its successor MMPDS for aerospace metals, or the material producer's certified data) rather than a nominal number from a catalogue; minimum values differ from typical ones by enough to matter.
