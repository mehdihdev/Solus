+++
title = "What a connector rating means: per-contact current under stated conditions, cycles, and locking"
kind = "principle"
audience = "fundamentals"
applicability = []
derivation = "solus_original"
confidence = 0.85
confidence_basis = "vendor_stated"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:electrical/connector_selection/jst-molex-xt-families-where-each-belongs", "corpus:electrical/connector_selection/connector-pitfalls"]
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
  { title = "Micro-Fit 3.0 connector system product specification", author = "Molex", identifier = "", url = "https://www.molex.com/" },
  { title = "PH connector series product catalogue", author = "JST Mfg.", identifier = "", url = "https://www.jst-mfg.com/" },
  { title = "USB Type-C Cable and Connector Specification", author = "USB Implementers Forum", identifier = "", url = "https://www.usb.org/" },
]
+++

A connector datasheet gives a current rating per contact, and the number only means something with its conditions attached: the wire gauge crimped to the contact, how many of the positions in the housing are carrying current at once, the ambient temperature, and the temperature rise the manufacturer allowed (commonly 30 °C). Load every pin in a 12-position housing and each contact is rated for less than the headline figure, because the contacts heat each other; the manufacturer's derating curve shows how much. A connector at its limit runs hot, the contact spring relaxes, resistance rises, and it runs hotter, which is the failure sequence behind melted connectors on motor leads.

The voltage rating comes from the clearance and creepage inside the housing and between adjacent contacts, and it is independent of the current rating.

Mating cycles are a lifetime specification. Wire-to-board families intended for assembly and occasional service are often rated for only a few dozen insertions; connectors designed for users, such as USB, are specified for thousands. A debug or battery connector that is plugged daily wears out a low-cycle contact in months, and worn contacts show up as intermittent power.

Locking, keying, and polarity are three separate features. A lock (latch, friction ramp, screw) keeps the connector mated under vibration. Keying prevents the plug entering a housing of the wrong kind or orientation. Polarity is the specific case of keying that stops a two-wire power connector being reversed. Cheap 2.54 mm headers have none of the three.

Strain relief is the connector's job to specify and the harness's job to provide: the housing's insulation grip or a nearby clamp must take the cable's weight and motion so the crimped contact carries only current. Molex, JST, and TE publish these ratings and derating data for every series; read the product specification, not the summary line in a distributor listing.
