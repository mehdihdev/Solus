+++
title = "Pitfall: the connector failures that stop robots — headers on motors, no keying, no strain relief"
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
related = ["corpus:electrical/connector_selection/connector-ratings-and-what-they-mean", "corpus:electrical/wire_gauge/stranded-vs-solid-crimp-vs-solder"]
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
  { title = "Quality Crimping Handbook", author = "Molex", identifier = "", url = "https://www.molex.com/" },
  { title = "IPC/WHMA-A-620 Requirements and Acceptance for Cable and Wire Harness Assemblies", author = "IPC", identifier = "IPC/WHMA-A-620", url = "https://www.ipc.org/" },
]
+++

Connectors are the most common single point of failure in a student or prototype robot, and the failures repeat.

Header pins carrying motor current. A 2.54 mm jumper contact is a prototyping part; run a gearmotor through it and the contact heats, the plastic softens, and the connection becomes intermittent under vibration. Symptoms look like a firmware or driver fault.

Every pin loaded at the headline rating. The per-contact rating assumes only some positions are carrying current; with all of them loaded, the derating curve applies and the connector runs beyond its temperature class. Melted housings on battery and driver connectors are almost always this.

No keying between voltages. Two identical connector families on one board, one at 24 V and one at 5 V, will eventually be swapped. Use different families, different pin counts, or a mechanical key per voltage.

Parallel pins for current. Contacts in parallel do not share current equally; resistance differences of a few milliohms put most of the current through one pin. Derate heavily or use a contact rated for the full current.

No strain relief. A cable whose weight or motion is carried by the crimped contact fatigues the strands at the barrel. A clamp or tie-down within a few centimetres of the connector, and a service loop, are part of the design.

Friction-fit where a latch was needed. Connectors near motors or on moving arms walk out under vibration; only a positive latch survives.

Exhausted mating cycles. A programming or battery connector plugged many times a day wears out a low-cycle contact in months.

Mixed contact platings and unbranded contacts. Tin against gold, or a clone terminal in a genuine housing, corrodes or fits loosely; keep plating and manufacturer consistent within a mated pair.

Check: measure the voltage across each power connector under full load; more than a few tens of millivolts means a hot contact. Tug-test every crimp. Photograph the harness so the next person can see what was designed rather than what was improvised.
