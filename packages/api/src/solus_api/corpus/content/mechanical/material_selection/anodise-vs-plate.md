+++
title = "Anodising is an insulator: surface finish decisions that affect the electrical team"
kind = "pitfall"
audience = "reference"
applicability = []
derivation = "solus_original"
confidence = 0.85
confidence_basis = "government_published"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:mechanical/material_selection/galling-and-galvanic-pairs", "corpus:mechanical/material_selection/common-robot-metals"]
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
  { title = "MIL-A-8625 — Anodic Coatings for Aluminum and Aluminum Alloys", author = "US Department of Defense", identifier = "MIL-A-8625", url = "https://quicksearch.dla.mil/" },
  { title = "ASTM B633 — Standard Specification for Electrodeposited Coatings of Zinc on Iron and Steel", author = "ASTM International", identifier = "ASTM B633", url = "https://www.astm.org/" },
]
+++

**Anodising** grows the aluminium's own oxide into a thick, hard, porous layer that is then sealed (and optionally dyed). **Plating** deposits a different metal — zinc, nickel, chrome — on top of the base metal. They solve overlapping problems (corrosion, wear, appearance) with different side effects, and one of those side effects regularly breaks a robot's electrical design.

**Anodised aluminium does not conduct.** Aluminium oxide is an excellent electrical insulator. A chassis that the electrical team is counting on as a ground return, a shield connection, or an ESD path will not be one if it has been anodised all over. The same goes for any part meant to bond a PCB mounting hole, a cable shield clamp, or a motor housing to frame ground. The fix is a drawing note that **masks specific areas** from anodising (around ground-stud holes, under standoffs and bonding straps), or a plated conductive coating (chemical conversion coating, "chromate" or its trivalent successors) where conductivity is required over the whole surface. This is a cross-domain interface: the mechanical drawing decides whether the electrical ground exists.

Other anodising facts that matter for design:

- The coating adds thickness on every surface — a small amount for decorative (Type II sulphuric) finishes, more for hardcoat (Type III). Roughly half of it grows inward and half outward, so toleranced bores and shafts change size; specify "dimensions apply after finish" or mask the fits. MIL-A-8625 is the usual specification and defines the types and classes.
- Hardcoat gives a very hard, wear-resistant surface (good for bearing surfaces and slides) but is brittle and slightly rough; it is not a lubricant.
- Anodising only works on aluminium (and titanium). Steel is plated or blackened instead.

**Plating** side effects:

- Plated coatings are conductive, so they keep a ground path — but a plated layer over a threaded hole changes the fit, and thick plating on a fine thread can bind it.
- Zinc plating (ASTM B633 for steel) protects steel sacrificially and is the cheap default for hardware; it is not a wear surface.
- Dissimilar plating on mating parts can itself create a galvanic pair. Zinc-plated screws in stainless are fine indoors and a corrosion cell outdoors.

Always ask two questions when a finish is specified: does any electrical connection depend on this surface conducting, and does any fit depend on this surface's size?
