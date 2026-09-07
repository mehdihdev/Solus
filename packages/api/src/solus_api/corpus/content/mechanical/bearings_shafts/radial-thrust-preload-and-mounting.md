+++
title = "Rolling bearings: radial versus thrust loads, preload, and locating the rings"
kind = "principle"
audience = "fundamentals"
applicability = []
derivation = "solus_original"
confidence = 0.85
confidence_basis = "vendor_stated"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:mechanical/fits_tolerances/choosing-fits-bearing-dowel-press", "corpus:mechanical/bearings_shafts/keyways-set-screws-clamping-hubs"]
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
  { title = "Rolling bearings (general catalogue) — bearing selection, mounting, and axial location", author = "SKF", identifier = "", url = "https://www.skf.com/" },
  { title = "ISO 281 — Rolling bearings — Dynamic load ratings and rating life", author = "ISO", identifier = "ISO 281", url = "https://www.iso.org/" },
  { title = "DIN 471 — Retaining rings for shafts — Normal type and heavy type", author = "DIN", identifier = "DIN 471", url = "https://www.din.de/" },
]
+++

A rolling bearing lets a shaft turn while carrying load, and it has a strong opinion about which *direction* that load comes from.

**Radial versus thrust.** A radial load pushes across the shaft (a belt pulling a pulley, a wheel bearing the robot's weight). A thrust (axial) load pushes along the shaft (a propeller, a lead screw, a wheel cornering). The common deep-groove ball bearing carries radial load well and a moderate thrust load; a cylindrical roller bearing carries more radial load and essentially no thrust; an angular-contact ball bearing or a tapered roller bearing carries both, but only thrust in *one* direction, so they are used in opposed pairs; a dedicated thrust bearing carries axial load only and falls apart under radial load. Identify every load's direction and magnitude before choosing a type; the catalogue gives ratings, and ISO 281 defines how a dynamic rating becomes a life at a given load.

**Preload** is a deliberate small axial force squeezing the rolling elements against the races so there is zero internal clearance. Without it a bearing has a little radial play, which appears as position error at the end of an arm and as noise under reversing load. Preload removes the play and stiffens the assembly, at the cost of more friction and heat and a shorter life if overdone. A pair of angular-contact bearings preloaded against each other by a shim, a spring (wave washer), or a nut is the standard arrangement for anything that must be stiff and accurate. Radially-loaded deep-groove bearings usually run with a small clearance instead, and are given a light axial preload with a wave washer only to quieten them.

**Locating the rings.** A bearing must be held in position axially or it will walk along the shaft. The pattern is one **locating** bearing per shaft — clamped to the shaft on one side by a shoulder and on the other by a retaining ring (DIN 471 external, DIN 472 internal) or a nut, and clamped in the housing the same way — and one **floating** bearing whose outer ring can slide axially so thermal growth of the shaft does not preload it to death. Two rigidly located bearings on one shaft is a common error that works on the bench and fails hot. Shoulders must bear on the ring face, not the seal or cage; acceptable shoulder height and fillet radius are in the catalogue.

Fits are the other half of mounting; the fits-and-tolerances topic covers which ring gets the tight one.
