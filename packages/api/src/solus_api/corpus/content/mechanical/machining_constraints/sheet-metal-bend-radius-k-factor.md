+++
title = "Sheet-metal bends: inside radius, K-factor, and bend allowance"
kind = "rule_of_thumb"
audience = "reference"
applicability = [{ key = "process", value = "sheet_metal" }]
derivation = "solus_original"
confidence = 0.75
confidence_basis = "rule_of_thumb"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:mechanical/fits_tolerances/process-tolerance-capability"]
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
  { title = "DIN 6935 — Cold bending of flat rolled steel products", author = "DIN", identifier = "DIN 6935", url = "https://www.din.de/" },
  { title = "Onshape Help — Sheet metal: K-factor, bend allowance, and bend radius settings", author = "Onshape (PTC)", identifier = "", url = "https://cad.onshape.com/" },
]
+++

When a sheet is bent, the outside of the bend stretches and the inside compresses. Somewhere between them is a **neutral axis** that keeps its length, and its position is what lets you predict how long the flat blank must be to produce a bent part of the right dimensions.

**K-factor** is the position of that neutral axis as a fraction of the sheet thickness `T`, measured from the inside face: `K = t / T`, where `t` is the neutral-axis depth. It is a number between 0 and 0.5 by definition (the neutral axis cannot be outside the sheet, and it moves toward the inside face as the bend gets tighter). For an inside radius `R` and a bend angle `θ` in degrees, the **bend allowance** — the arc length of the neutral axis, which is the flat length consumed by the bend — is

```
BA = (π / 180) · θ · (R + K · T)
```

The flat pattern is the sum of the flat leg lengths (measured to the start of each bend) plus a bend allowance for each bend. CAD sheet-metal tools do this arithmetic; feed them the wrong `K` and every hole near a bend lands in the wrong place.

**Defaults, and their limits:**

- **Inside bend radius**: about one sheet thickness (`R ≈ T`) is a safe, common default for mild steel and soft-temper aluminium on a standard press brake. Tighter radii risk cracking on the outside of the bend, especially in harder aluminium tempers (6061-T6 cracks where 5052-H32 folds happily) and across the grain direction. DIN 6935 gives minimum bend radii by material and thickness for steel; the aluminium producer's data sheet gives them for aluminium.
- **K-factor**: for air bending with `R ≈ T`, values around 0.33–0.45 are typical; harder materials and larger radii push it toward 0.5, tight radii and soft materials toward 0.33. Do not guess: ask the shop for the K-factor or bend table they use, or bend a test coupon and measure it. A shop's bend table beats any formula.
- **Hole-to-bend distance**: a hole closer to the bend than roughly 2 × T plus the bend radius will distort into an oval as the material flows. Move it, or cut it after bending.
- **Minimum flange length**: a flange shorter than about 4 × T gives the press-brake die nothing to hold.
- **Bend relief**: where a bend ends part-way along an edge, cut a relief slot at the end of the bend line so the material does not tear.

Bent dimensions are the least precise part of a sheet-metal part; put the tolerances on features cut in the flat, and let a slot or an adjustable fastener absorb the bend variation.
