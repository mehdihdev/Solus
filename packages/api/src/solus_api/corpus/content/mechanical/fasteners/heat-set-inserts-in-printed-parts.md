+++
title = "Heat-set inserts in FDM parts: hole sizing, installation, and pull-out"
kind = "procedure"
audience = "fundamentals"
applicability = [{ key = "process", value = "fdm" }]
derivation = "solus_original"
confidence = 0.75
confidence_basis = "rule_of_thumb"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:mechanical/fasteners/thread-engagement-length", "corpus:mechanical/machining_constraints/fdm-orientation-overhangs-bridging", "corpus:mechanical/material_selection/printed-plastics-temperature-limits"]
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
  { title = "Heat-Set Inserts for Plastic — catalogue pages and installation notes", author = "McMaster-Carr", identifier = "", url = "https://www.mcmaster.com/" },
  { title = "ISO/ASTM 52910 — Additive manufacturing — Design — Requirements, guidelines and recommendations", author = "ISO/ASTM", identifier = "ISO/ASTM 52910", url = "https://www.iso.org/" },
]
+++

Tapping threads directly into an FDM print gives threads made of layer lines and a few perimeters; they strip under modest torque and creep loose under sustained preload. A brass heat-set insert melts into the plastic and gives a proper metal thread. Use one for any fastener that will be tightened more than once or carries a real load.

**Procedure**

1. **Pick the insert for the plastic.** Inserts sold for thermoplastics have external knurls or barbs designed to be re-flowed into; inserts intended for moulded-in or press-in use in other materials will not hold. Choose a length at least as long as the fastener is strong for: a short insert in a thin wall pulls out before the screw is stressed.
2. **Model the hole to the insert maker's specification**, not to the insert's outer diameter. Every insert series publishes a recommended hole diameter for thermoplastics, slightly smaller than the insert's largest knurl so the plastic flows into the knurls. Because FDM holes print undersize, either model the hole at the specified diameter plus your printer's measured offset, or model it slightly small and drill to size after printing (the more repeatable option).
3. **Give the hole enough wall.** A boss of at least about 1.5–2 mm of solid wall around the insert, with extra perimeters in the slicer, is the difference between an insert that holds and one that splits the boss on installation. Make the hole deeper than the insert so displaced plastic and the screw tip have somewhere to go.
4. **Install with a soldering iron and a purpose-made tip** at a temperature a little above the plastic's melting range — the insert should sink under light, steady pressure over a few seconds. Too hot and the plastic degrades and gets glassy; too cold and you push instead of melt, cracking the boss. Stop flush or a fraction below the surface; a press-fit installation jig keeps the insert square, which matters more than it looks.
5. **Let it cool before loading.** The plastic re-solidifies around the knurls; torquing a screw in immediately spins the insert.

**Limits.** Pull-out strength is set by the plastic, not the brass: PLA holds well at room temperature and softens near 60 °C, where an insert under preload will creep and back out; PETG and ABS are better; nylon and glass-filled materials better still. Where the joint sees heat, sustained load, or safety consequences, a through-bolt with a nut, a captive nut pocket, or a metal sub-frame beats any insert.
