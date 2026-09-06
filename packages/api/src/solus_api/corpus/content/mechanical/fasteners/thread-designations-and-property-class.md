+++
title = "Reading a fastener callout: M6×1, 1/4-20 UNC, and property class 8.8"
kind = "glossary"
audience = "fundamentals"
applicability = []
derivation = "solus_original"
confidence = 0.9
confidence_basis = "standard_derived"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:mechanical/fasteners/preload-not-torque"]
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
  { title = "ISO 68-1 — ISO general purpose screw threads — Basic profile — Part 1: Metric screw threads", author = "ISO", identifier = "ISO 68-1", url = "https://www.iso.org/" },
  { title = "ISO 261 — ISO general purpose metric screw threads — General plan", author = "ISO", identifier = "ISO 261", url = "https://www.iso.org/" },
  { title = "ISO 898-1 — Mechanical properties of fasteners made of carbon steel and alloy steel — Part 1: Bolts, screws and studs with specified property classes", author = "ISO", identifier = "ISO 898-1", url = "https://www.iso.org/" },
  { title = "ASME B1.1 — Unified Inch Screw Threads (UN and UNR Thread Form)", author = "ASME", identifier = "ASME B1.1", url = "https://www.asme.org/" },
]
+++

**Metric (ISO) threads.** `M6×1` means a metric thread of 6 mm nominal (major) diameter with a 1 mm pitch — the distance from one thread crest to the next. Each nominal size has one **coarse** pitch that is the default and is usually omitted (`M6` alone means `M6×1`; `M8` means `M8×1.25`; `M10` means `M10×1.5`), plus one or more **fine** pitches that must be written out (`M8×1`). Fine threads give slightly more tensile area and finer adjustment but strip and cross-thread more easily, so robots use coarse unless there is a reason. A trailing tolerance class such as `6g` (external) or `6H` (internal) may follow; the default classes are what any catalogue fastener is made to.

**Unified (inch) threads.** `1/4-20 UNC` is a 1/4 inch nominal diameter with 20 threads per inch (so the pitch is 1/20 inch, about 1.27 mm), in the coarse series. `UNF` is the fine series (`1/4-28 UNF`). Numbered sizes below 1/4 inch read the same way: `#10-32` is a size-10 diameter with 32 threads per inch. Class `2A`/`2B` is the ordinary commercial fit for external/internal threads. Metric and unified threads never interchange — an `M6` will start into a `1/4-20` hole and then jam.

**Strength: property class and grade.** Metric steel fasteners carry a two-part **property class** such as `8.8`, `10.9`, or `12.9` (ISO 898-1). The digits encode the strength: the first number times 100 is the nominal tensile strength in MPa, and the two numbers multiplied together times 10 is the nominal yield (or proof-stress) in MPa. So `8.8` is about 800 MPa tensile and 640 MPa yield; `12.9` is about 1200 MPa and 1080 MPa. Inch fasteners use **SAE grades** (Grade 5 roughly comparable to 8.8, Grade 8 roughly comparable to 10.9), marked with radial lines on the head. Stainless fasteners are marked differently (`A2-70`, `A4-80`: alloy group then tensile strength in tens of MPa) and are generally weaker than 8.8 carbon steel — a common surprise.

The **proof load** in the standard is the load a bolt must carry without permanent set; it is the number preload targets are calculated from. Take proof loads and thread stress areas from ISO 898-1 and the thread standards rather than from memory.
