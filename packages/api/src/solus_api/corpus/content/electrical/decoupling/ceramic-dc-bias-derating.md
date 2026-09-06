+++
title = "Pitfall: a Class II ceramic capacitor loses much of its capacitance under DC bias"
kind = "pitfall"
audience = "reference"
applicability = []
derivation = "solus_original"
confidence = 0.9
confidence_basis = "vendor_stated"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:electrical/decoupling/value-spread-bulk-vs-local"]
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
  { title = "Basics of Capacitors (technical lesson series)", author = "Murata Manufacturing", identifier = "", url = "https://www.murata.com/" },
  { title = "KEMET ceramic capacitor technical documentation", author = "KEMET", identifier = "", url = "https://www.kemet.com/" },
]
+++

The nominal value printed on a multilayer ceramic capacitor is measured at a small AC signal with no DC across it. Class II dielectrics (X5R, X7R, and similar) are ferroelectric, and a DC voltage across them reduces the effective capacitance. The effect grows with the applied voltage as a fraction of the rated voltage, and it is worse in smaller packages, because the same voltage rating is achieved with thinner dielectric layers and a higher field. A 10 µF 0402 part rated 6.3 V, operated at 5 V, can deliver a small fraction of 10 µF; a 10 µF 1206 rated 25 V at the same 5 V loses far less.

On top of bias, Class II parts also drift with temperature (the code tells you the band and tolerance) and age, losing a few percent of capacitance per decade of hours after their last heating above the Curie point.

Where this bites: the bulk capacitance a buck regulator's stability depends on; an ADC reference bypass that turns out to be much smaller than the datasheet assumed; a bootstrap or timing capacitor whose value sets a frequency; an input filter whose ripple rises with battery voltage; anywhere someone chose the smallest package that had the right number on it.

What to check: read the manufacturer's DC-bias characteristic curve for the exact part number, not the family; it is on the vendor's site and in their simulation tools. Rate the capacitor at least twice the working voltage if package space allows, or step up a package size. For values that must be accurate, use Class I (C0G/NP0) dielectric, which has negligible bias and temperature dependence but is only available in small values, or a film or polymer type. Capacitance does not appear in a schematic-level check, so this is one to review at part selection.
