+++
title = "A drilled hole is not a precision hole: drill, then ream or bore"
kind = "pitfall"
audience = "reference"
applicability = []
derivation = "solus_original"
confidence = 0.85
confidence_basis = "consensus"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:mechanical/fits_tolerances/fit-classes-and-reading-h7-g6", "corpus:mechanical/fits_tolerances/choosing-fits-bearing-dowel-press", "corpus:mechanical/machining_constraints/cnc-milling-dfm-basics"]
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
  { title = "ASME B94.11M — Twist Drills", author = "ASME", identifier = "ASME B94.11M", url = "https://www.asme.org/" },
  { title = "ASME B94.2 — Reamers", author = "ASME", identifier = "ASME B94.2", url = "https://www.asme.org/" },
  { title = "ISO 286-1 — ISO code system for tolerances on linear sizes — Part 1", author = "ISO", identifier = "ISO 286-1", url = "https://www.iso.org/" },
]
+++

The failure: a drawing calls for an `H7` bearing bore or a dowel hole, the shop drills it to the nominal size, and the bearing rattles or the dowel will not go in. A twist drill is a roughing tool. It has two cutting lips that never quite match, it flexes, it wanders as it enters, and it tends to cut slightly oversize, slightly out of round, and slightly off position — good enough for a clearance hole, nowhere near a fit.

What each operation delivers:

- **Drilling** — fast, cheap, holds roughly the general-tolerance class of the drawing and no better. Fine for fastener clearance holes, tap drills, and any hole whose fit does not matter. Errors of a tenth of a millimetre or more are normal.
- **Reaming** — a multi-flute tool that follows a drilled hole slightly undersize and shaves it to a precise diameter with good roundness and finish. This is how a hole reaches the `IT6`–`IT8` grades that the common fits (`H7` bores, dowel holes) demand. A reamer does **not** correct position; it follows the drilled hole, so the drill must be on location (spot drill first, or drill on a machine with a rigid setup).
- **Boring** — a single-point tool on a machine spindle that cuts diameter *and* fixes position, because it cuts to wherever the spindle axis is. Slower and more skilled, but it is the answer for a large-diameter precise bore, a bore whose position is critical (two bearing bores that must be coaxial), or a size for which no reamer is stocked.
- **Interpolated milling** — an end mill driven in a circle. Fine for medium accuracy; verify with a gauge before relying on it for a fit.

Design rules that fall out of this:

- Specify the *fit* (`Ø8 H7`) and let the machinist choose the method; but expect to pay for it, and do not specify a fit on a hole that only needs clearance.
- Keep reamed and bored holes to standard sizes (whole millimetres and the standard fractional or letter drill and reamer sizes); an odd diameter means a special tool.
- Give a reamer room: a blind reamed hole needs extra depth for the chamfered tool lead, and a through hole reams more accurately than a blind one.
- Two holes that must be coaxial should be bored in one setup or line-reamed together; two independently drilled and reamed holes on opposite walls will not line up to bearing standards.
- For printed parts, the same logic applies with a twist: print undersize, then drill or ream to the fit — the printer is the "drill" here.
