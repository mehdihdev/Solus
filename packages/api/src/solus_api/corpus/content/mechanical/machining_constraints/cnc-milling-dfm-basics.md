+++
title = "Designing for a CNC mill: corner radii, tool reach, and minimum wall"
kind = "principle"
audience = "fundamentals"
applicability = [{ key = "process", value = "cnc_mill" }]
derivation = "solus_original"
confidence = 0.8
confidence_basis = "consensus"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:mechanical/machining_constraints/drill-vs-ream", "corpus:mechanical/fits_tolerances/process-tolerance-capability"]
further_reading = [
  { title = "Machinery's Handbook", author = "Oberg, Jones, Horton, Ryffel", identifier = "" },
]
corpus_version = "0.1.0"
revised_in = "0.1.0"

[provenance]
source_class = "solus_authored"
source_title = "Solus engineering corpus"
source_publisher = "Solus"
source_license = "solus-proprietary"
accessed_at = 2026-09-06
checked_against = [
  { title = "ASME B94.19 — Milling Cutters and End Mills", author = "ASME", identifier = "ASME B94.19", url = "https://www.asme.org/" },
  { title = "ISO 2768-1 — General tolerances — Part 1: Tolerances for linear and angular dimensions without individual tolerance indications", author = "ISO", identifier = "ISO 2768-1", url = "https://www.iso.org/" },
]
+++

A milled part is made by a spinning cylinder removing material. Everything a mill cannot do follows from that one fact, and a designer who keeps the cylinder in mind gets cheaper, faster, more accurate parts.

**Internal corners are round.** A vertical internal corner in a pocket has a radius at least equal to the end mill's radius — a truly sharp internal corner does not exist. Worse, a corner radius *exactly* equal to the tool radius forces the tool to stop and pivot in the corner, which chatters and leaves a mark. Draw pocket corner radii a little larger than the radius of a standard tool (say 3.2–3.5 mm for a 6 mm tool) and the machinist can cut it in one smooth pass. External corners can be sharp; they are not the problem. If a mating part genuinely needs a sharp internal corner, put a **relief** — a small round "dog-bone" or "T-bone" cut into the corner so the mating sharp edge clears.

**Fillets between a pocket floor and its walls** need a ball or corner-radius tool and cost time; a plain flat end mill leaves that corner sharp for free.

**Reach.** A tool cutting deep relative to its diameter deflects, chatters, and holds worse tolerance. Depth up to about three to four times the tool diameter is routine; beyond that expect extended-reach tools, slower feeds, taper on the wall, and higher cost. A deep narrow slot is the expensive shape: its width sets the tool diameter and its depth sets the reach. Widen the slot, shorten it, or split the part.

**Minimum wall.** Thin walls vibrate under the cutter and bow away from it. About 0.8 mm is a practical floor in aluminium for short walls and around 1.5 mm in plastics; taller walls need to be thicker in proportion. Where a thin wall is unavoidable, make it short or add a rib.

**Setups.** Every face that must be machined from a different direction is another setup, and each setup adds a fixturing error and cost. A part machinable from one side (all pockets and holes from the top) is the cheapest; through-features that must be reached from the back add a flip. Design so critical features share a setup — they will then be located to each other far better than the general tolerance implies.

**Tolerances.** Put a general-tolerance note (ISO 2768 class or the shop's default) on the drawing and tolerance individually only what must fit; see the process-capability chunk.
