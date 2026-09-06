+++
title = "A bolt is a spring: preload is the goal and torque is a poor proxy for it"
kind = "principle"
audience = "fundamentals"
applicability = []
derivation = "solus_original"
confidence = 0.9
confidence_basis = "government_published"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:mechanical/fasteners/thread-engagement-length", "corpus:mechanical/fasteners/locking-methods", "corpus:mechanical/fasteners/thread-designations-and-property-class"]
further_reading = [
  { title = "Shigley's Mechanical Engineering Design", author = "Budynas, Nisbett", identifier = "" },
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
  { title = "Fastener Design Manual (NASA Reference Publication 1228)", author = "Barrett, NASA Lewis Research Center", identifier = "NASA-RP-1228", url = "https://ntrs.nasa.gov/" },
  { title = "NASA-STD-5020 — Requirements for Threaded Fastening Systems in Spaceflight Hardware", author = "NASA", identifier = "NASA-STD-5020", url = "https://standards.nasa.gov/" },
]
+++

A bolted joint works by stretching the bolt. Tightening pulls the bolt slightly longer, and that stretch — the **preload** — clamps the parts together. A joint with enough preload does not slip, does not separate under the working load, and does not fatigue the bolt, because the clamped parts carry most of the external load and the bolt only sees a fraction of it. Nearly every bolted-joint failure in a robot (a loose motor mount, a wobbling wheel hub, a sheared shoulder bolt) is a preload failure first.

Torque is what you can measure with a wrench, so it is what drawings specify. But torque and preload are linked only through friction: for a dry or lightly oiled steel fastener, most of the applied torque — on the order of 85–90 % — is spent overcoming friction under the head and in the threads, and only the remainder stretches the bolt. The common short-form relation is

```
T ≈ K · F · d      T torque, F preload, d nominal diameter
```

where `K` is a "nut factor" that lumps all the friction together. `K ≈ 0.2` is the usual textbook default for plain steel, but it swings widely with lubrication, plating, surface finish, and whether the joint has been tightened before. That is why torque-controlled tightening delivers preload with a scatter widely quoted at ±25 % or worse. A stainless bolt into an aluminium tapped hole, lubricated with whatever was on the technician's fingers, does not have the K value the table assumed.

What to do with this:

- Design so that ±25 % preload scatter is acceptable: choose bolt size and grade with margin, and do not rely on one small fastener at the edge of its capacity.
- Target a preload in the region of 65–75 % of the bolt's proof load for reusable joints; property class or grade tells you the proof load (see the designation chunk).
- Specify the lubrication condition along with the torque, because a torque value without it is meaningless.
- Where preload really matters (a flexure clamp, a high-cycle joint), measure it — turn-of-nut, stretch, or a load-indicating method — instead of trusting torque.
- Re-torque after the first thermal or load cycles on soft or painted joints; embedding relaxes preload.
