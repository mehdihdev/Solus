+++
title = "PLA, PETG, ABS, nylon, POM: temperature limits and where each fails"
kind = "reference_value"
audience = "reference"
applicability = [{ key = "process", value = "fdm" }]
derivation = "solus_original"
confidence = 0.7
confidence_basis = "consensus"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:mechanical/material_selection/stiffness-vs-strength", "corpus:mechanical/fasteners/heat-set-inserts-in-printed-parts", "corpus:mechanical/machining_constraints/fdm-orientation-overhangs-bridging"]
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
  { title = "ISO 75-1 — Plastics — Determination of temperature of deflection under load — Part 1: General test method", author = "ISO", identifier = "ISO 75-1", url = "https://www.iso.org/" },
  { title = "ASTM D648 — Standard Test Method for Deflection Temperature of Plastics Under Flexural Load in the Edgewise Position", author = "ASTM International", identifier = "ASTM D648", url = "https://www.astm.org/" },
  { title = "ISO 11357-2 — Plastics — Differential scanning calorimetry (DSC) — Part 2: Determination of glass transition temperature", author = "ISO", identifier = "ISO 11357-2", url = "https://www.iso.org/" },
]
+++

A thermoplastic part does not fail at its melting point; it fails when it gets soft enough to creep under whatever load it carries. Two numbers on a filament's technical data sheet tell you where that is: the **glass transition temperature** (Tg, measured by DSC per ISO 11357-2), above which an amorphous plastic turns rubbery, and the **heat deflection temperature** (HDT, per ISO 75 or ASTM D648), the temperature at which a test bar sags a set amount under a set load. HDT is the more useful design number because it includes load; use the higher-load value for structural parts.

Typical values as widely published for unfilled FDM grades — the exact number belongs to the specific filament, so take it from that data sheet:

| Material | Softens around | Character | Fails when… |
|----------|----------------|-----------|-------------|
| **PLA** | ~55–65 °C | Stiff, brittle, prints easily | The part sits in a parked car, next to a motor or driver, or under sustained preload (creeps even at room temperature) |
| **PETG** | ~75–85 °C | Tougher than PLA, some chemical resistance | Needs tight tolerances (strings, oozes); is used for high-cycle snap fits (scratches and whitens) |
| **ABS / ASA** | ~95–105 °C | Tough, machinable, ASA is UV-stable | Printed on an open printer (warps and cracks along layers); needs dimensional accuracy on large parts (shrinks) |
| **Nylon (PA6, PA12, and CF-filled)** | Tg is low (~50 °C) but semicrystalline, so it keeps useful strength well above Tg; HDT of filled grades is much higher | Tough, wear-resistant; gears and living hinges | Absorbs moisture (swells and softens; dry before printing); unfilled grades warp badly |
| **POM (acetal)**, usually machined not printed | HDT roughly 100–110 °C region | Low friction, dimensionally stable, excellent for bushings, gears, sliding parts | You need to glue it (almost nothing bonds to it); it is exposed to strong acids |

Working rules:

- A printed part within a hand's width of a motor, driver, battery, or power resistor should not be PLA.
- Sustained load plus warmth means creep in every plastic here; a preloaded joint in PLA loosens by itself within days at 40–50 °C. Use metal inserts or through-bolts.
- Carbon-fibre-filled grades are stiffer and more heat-resistant but *not* stronger across layers.
- These plastics are one to two orders of magnitude less stiff than aluminium; a printed bracket that feels stiff still flexes enough to matter for a camera or encoder mount.
