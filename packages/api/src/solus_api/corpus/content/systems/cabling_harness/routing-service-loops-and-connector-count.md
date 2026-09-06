+++
title = "Route harnesses away from motion, leave service loops, and count your connectors"
kind = "rule_of_thumb"
audience = "reference"
applicability = []
derivation = "solus_original"
confidence = 0.8
confidence_basis = "consensus"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = []
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
  { title = "Workmanship Standard for Crimping, Interconnecting Cables, Harnesses, and Wiring", author = "NASA", identifier = "NASA-STD-8739.4", url = "https://www.nasa.gov/" },
  { title = "Continuous-flex cable and cable carrier design guidance", author = "igus", identifier = "chainflex and e-chain technical documentation", url = "https://www.igus.com/" },
  { title = "Connector mating cycle and current derating documentation", author = "Molex", identifier = "product specifications", url = "https://www.molex.com/" },
]
+++

A harness is a mechanical part that happens to carry electricity, and it fails mechanically: flexed until a conductor breaks, chafed through on an edge, or pulled until a crimp lets go. Rules of thumb, each with its limit.

- A cable never crosses a joint by accident. Where it must cross one, it does so in a designed flex section: a loop or a cable carrier whose bend radius is generous, anchored on both sides of the joint so the flexing happens in the section built for it. Cable vendors publish a minimum bend radius as a multiple of the cable's outer diameter, and the figure for continuous flexing is much larger than the figure for a one-time installation bend; a cable chosen from a static catalogue will fail early in a moving joint.
- Strain relief at every connector. The cable should be clamped so that tension goes into the clamp and the housing, never into the crimp or the solder joint. A connector that can be pulled out by the cable has no strain relief.
- Leave a service loop. Enough slack at each end to unplug, inspect, and re-terminate a connector once without rebuilding the harness.
- Label both ends of every cable with the same identifier that appears in the interface record, and label connectors with their mating pair. The person who needs the label is the one who did not build the harness.
- Separate power from signal. Motor phase leads and switching supply cables carry fast edges; a signal cable run parallel to them for any length picks them up. Route them apart, cross at right angles when they must cross, use twisted pairs for differential signals, and keep encoder and sensor cables on the far side of the chassis from motor leads.
- Count connectors as a reliability metric. Every mated pair is a place for intermittent contact, mis-mating, and fretting under vibration, so the number of connectors between a sensor and its controller is a rough measure of how often that channel will drop out. Remove the ones that exist only for convenience, and make the rest keyed, locking, and rated for the mating cycles you will use.
- Under vibration, anything that can move will chafe. No cable ties over sharp edges, no ties tightened until they deform the insulation, grommets at every pass-through, and bundles supported often enough that they cannot swing.

Inspect the harness whenever the mechanism is opened. Discolouration, flattened insulation, and a connector that "just needed reseating" are early warnings, not fixes.
