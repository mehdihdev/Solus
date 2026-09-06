+++
title = "Choosing decoupling values: local 100 nF class, bulk per rail, and the anti-resonance caveat"
kind = "rule_of_thumb"
audience = "reference"
applicability = []
derivation = "solus_original"
confidence = 0.8
confidence_basis = "rule_of_thumb"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:electrical/decoupling/what-a-decoupling-capacitor-does"]
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
  { title = "MT-101 Decoupling Techniques", author = "Analog Devices", identifier = "MT-101", url = "https://www.analog.com/" },
  { title = "Basics of Capacitors (technical lesson series)", author = "Murata Manufacturing", identifier = "", url = "https://www.murata.com/" },
]
+++

A defensible default network for a digital or mixed-signal board:

| Role | Where | Typical value | Job |
| --- | --- | --- | --- |
| Local | one per IC power pin, right at the pin | 100 nF ceramic (0402 or 0603) | supplies the switching spike |
| Group bulk | one per rail per cluster of ICs | 1–10 µF ceramic | recharges the locals, covers the middle frequencies |
| Rail bulk | at the regulator output | tens to hundreds of µF, per the regulator datasheet | holds the rail through load steps; sets regulator stability |

Two refinements the default hides.

The value is not the point at high frequency. A ceramic capacitor's impedance above its self-resonance is set by its package inductance, so a 1 µF 0402 part is as good as a 100 nF 0402 at the frequencies that matter for a modern MCU, and better below them. If the datasheet allows, one larger-value small-package capacitor per pin often beats a 100 nF part, and the "100 nF" habit dates from larger packages.

Spreading values by decades (10 nF, 100 nF, 1 µF in parallel) is sometimes recommended to broaden the low-impedance band, but parallel capacitors of different values create an anti-resonance peak between their self-resonant frequencies where the combined impedance is worse than either alone. MT-101 discusses this. If you spread values, keep the ratio modest (about 10:1 at most) and prefer several of the same value when in doubt.

Limits: follow the IC datasheet where it is specific, especially for RF parts, PLL supplies, and ADC references, which often want a particular value or a series ferrite. For the rail bulk, the regulator's stability requirements (minimum output capacitance, ESR range) override any rule of thumb.
