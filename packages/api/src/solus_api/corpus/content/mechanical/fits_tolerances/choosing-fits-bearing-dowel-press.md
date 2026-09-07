+++
title = "Picking a fit: bearing seats, dowel pins, and press fits"
kind = "rule_of_thumb"
audience = "reference"
applicability = []
derivation = "solus_original"
confidence = 0.75
confidence_basis = "rule_of_thumb"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:mechanical/fits_tolerances/fit-classes-and-reading-h7-g6", "corpus:mechanical/bearings_shafts/radial-thrust-preload-and-mounting"]
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
  { title = "Rolling bearings (general catalogue) — shaft and housing tolerance recommendations", author = "SKF", identifier = "", url = "https://www.skf.com/" },
  { title = "ISO 8734 — Parallel pins, of hardened steel and martensitic stainless steel (Dowel pins)", author = "ISO", identifier = "ISO 8734", url = "https://www.iso.org/" },
  { title = "ISO 286-1 — ISO code system for tolerances on linear sizes — Part 1", author = "ISO", identifier = "ISO 286-1", url = "https://www.iso.org/" },
]
+++

Defaults that work for the three fits a robot designer specifies most often. Each has a limit stated; when your case is outside it, go to the referenced tables instead of stretching the rule.

**Rolling-bearing seats.** The ring that rotates relative to the load direction needs a tight fit so it cannot creep and wear its seat; the ring that is stationary relative to the load can be looser so the bearing can be assembled and can float axially. For the common case of a rotating shaft carrying a fixed-direction load (a wheel, a pulley, a gear), that means the **shaft** gets a light interference (shaft classes in the `k`–`m` region) and the **housing** gets a close clearance or transition (`H7` or `J7`). Bearing makers publish the exact class per bearing size, load, and whether the housing is split or solid — take it from there, not from this paragraph. Limit: this is for small and medium ball bearings; thin-section, needle, and high-load applications have their own tables.

**Dowel pins.** Standard hardened dowels (ISO 8734) are ground to an `m6` shaft tolerance, so the fit is decided entirely by the hole. Press one part, slip the other: the press-side hole is reamed to give a light interference against `m6` (an `H7` reamed hole is the usual choice, giving a transition-to-light-press result), and the slip-side hole is reamed a class larger so the mating part locates but can be lifted off. Use two dowels, not one (one dowel does not fix rotation) and not three (three over-constrain).

**Press fits for retention.** A shaft pressed into a hub to carry torque by friction alone needs a real interference class (`p6`, `s6`, or heavier against an `H7` hole), and the holding force is only as good as the surface finish, the hoop stress the hub can take, and the temperature range — aluminium hubs on steel shafts loosen as they warm because aluminium expands roughly twice as fast. Beyond a few newton-metres, or for anything that must be disassembled, add a key, a clamp, or a fastener rather than relying on friction from the fit.
