+++
title = "Galling and galvanic pairs: the two dissimilar-metal problems"
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
related = ["corpus:mechanical/material_selection/common-robot-metals", "corpus:mechanical/fasteners/thread-engagement-length", "corpus:mechanical/material_selection/anodise-vs-plate"]
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
  { title = "MIL-STD-889 — Dissimilar Metals", author = "US Department of Defense", identifier = "MIL-STD-889", url = "https://quicksearch.dla.mil/" },
  { title = "ASTM G98 — Standard Test Method for Galling Resistance of Materials", author = "ASTM International", identifier = "ASTM G98", url = "https://www.astm.org/" },
  { title = "Fastener Design Manual (NASA Reference Publication 1228)", author = "Barrett, NASA Lewis Research Center", identifier = "NASA-RP-1228", url = "https://ntrs.nasa.gov/" },
]
+++

Two failures with similar names and nothing else in common.

**Galling** is cold welding under sliding contact. When two surfaces of the same or similar soft, ductile metal slide under pressure, their oxide layers rub off, bare metal touches bare metal, and the surfaces seize and tear. The classic case is a **stainless steel screw in a stainless steel nut or tapped hole**: it turns smoothly, then suddenly locks solid part-way in and cannot be removed without destroying it. Aluminium on aluminium and titanium on titanium do the same.

Prevent it by:

- not pairing like with like — a stainless screw into a plated-steel or brass nut, or a different stainless grade with a different hardness on each side;
- lubricating threads with anti-seize, and driving slowly (heat accelerates galling);
- using a nylon-insert or coated nut, which puts a third material between the threads;
- avoiding fine threads in stainless, which gall more readily.

**Galvanic corrosion** needs no motion at all. Two metals far apart in the galvanic series, electrically connected, with an electrolyte (rain, condensation, sweat, coolant) between them form a battery; the more active (anodic) metal corrodes at a rate set by how far apart they are and by the relative areas. In a robot the usual pairs are a **stainless or plated-steel fastener in an aluminium part**, **carbon fibre (which behaves like a noble metal) against aluminium**, and aluminium on a steel frame. The aluminium is the anode and loses. A small anode next to a large cathode corrodes fastest, so a small aluminium bracket bolted to a large carbon plate is the worst case. Corrosion products in a threaded hole swell and can strip or crack it.

Prevent it by:

- keeping the electrolyte out — sealed, dry, or coated (anodising and paint work by removing the electrical path or the electrolyte contact);
- isolating the pair with a non-conductive washer, sleeve, or gasket, or a barrier film between carbon fibre and aluminium;
- choosing pairs close together in the galvanic series (MIL-STD-889 groups metals for this purpose and is the reference to consult);
- if a sacrifice is unavoidable, making the *cheap, replaceable* part the anode — a zinc-plated steel screw corroding is better than the tapped aluminium housing it sits in.

Check any joint that sees moisture, dissimilar metals, and electrical continuity together. Two out of three is fine; all three is a corrosion cell.
