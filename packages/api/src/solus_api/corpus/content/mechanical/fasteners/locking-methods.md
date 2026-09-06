+++
title = "Why fasteners loosen under vibration, and which locking methods actually work"
kind = "pitfall"
audience = "reference"
applicability = [{ key = "environment", value = "vibration" }]
derivation = "solus_original"
confidence = 0.85
confidence_basis = "government_published"
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
  { title = "Fastener Design Manual (NASA Reference Publication 1228)", author = "Barrett, NASA Lewis Research Center", identifier = "NASA-RP-1228", url = "https://ntrs.nasa.gov/" },
  { title = "NASA-STD-5020 — Requirements for Threaded Fastening Systems in Spaceflight Hardware", author = "NASA", identifier = "NASA-STD-5020", url = "https://standards.nasa.gov/" },
]
+++

The failure: a motor mount or wheel hub is tight on the bench and loose after an hour of driving. Vibration does not "unscrew" a fastener by shaking it round; it lets the clamped parts slip sideways a tiny amount relative to each other, and each micro-slip lets the thread helix ratchet back a fraction of a turn. Once preload drops below the level needed to stop the slip, loosening runs away. The first defence is therefore **adequate preload** in a joint stiff enough not to slip — a locking feature is insurance for when preload is lost, not a substitute for it.

What works and what does not:

- **Split (spring) lock washers**: widely regarded as ineffective as a locking device once the joint is fully tightened — they flatten out and behave like a plain washer. NASA's fastener guidance says as much. Do not count them as a locking method.
- **Prevailing-torque nuts and screws** (nylon-insert "nyloc", all-metal deformed-thread, or a nylon patch on the screw): these resist rotation by friction in the threads independent of preload, so they hold even when the joint has relaxed. Nylon inserts lose effectiveness after a few reuses and above roughly 120 °C; all-metal types tolerate heat and more cycles. This is the standard answer for robot structure fasteners.
- **Thread-locking adhesive** (anaerobic): effective, cheap, and easy to inspect if you use a coloured grade. Removable grades come apart with hand tools; high-strength grades need heat. Adhesive needs clean, oil-free threads and does not cure well on some plastics and passive metals without an activator.
- **Serrated flange or wedge-lock washer pairs**: work by cam action and are effective for hard-surfaced joints; useless on soft or painted surfaces that they simply dig into.
- **Positive locking** (safety wire, tab washers, castellated nut and cotter pin, retaining plate): the only class that does not rely on friction at all. Appropriate where a fastener falling out is a safety issue — a wheel, an arm joint over a person.
- **Jam nuts**: better than nothing, but easy to install wrong and give inconsistent results.

Check, for any joint that has loosened once: was preload adequate (see the preload chunk)? Is the joint stack stiff, or does it include a plastic part, gasket, or paint that creeps? Does the fastener bottom out in a blind hole or on a washer stack before it clamps the parts? Fix those before adding a stronger locking method.
