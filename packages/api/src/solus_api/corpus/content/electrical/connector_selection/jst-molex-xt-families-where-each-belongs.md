+++
title = "Which connector family for which job: JST, Molex, XT, and header pins in a robot"
kind = "rule_of_thumb"
audience = "reference"
applicability = []
derivation = "solus_original"
confidence = 0.75
confidence_basis = "vendor_stated"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:electrical/connector_selection/connector-ratings-and-what-they-mean"]
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
  { title = "SH, GH, PH and XH connector series product catalogues", author = "JST Mfg.", identifier = "", url = "https://www.jst-mfg.com/" },
  { title = "Micro-Fit 3.0 and Mini-Fit Jr. connector system product specifications", author = "Molex", identifier = "", url = "https://www.molex.com/" },
]
+++

Catalogue ceilings below are the manufacturer's maximum per contact with the largest permitted wire; the real figure for your wire and pin count is lower, so read the product specification. The XT family is made by Amass and named for its nominal current.

| Family | Pitch | Catalogue ceiling | Locks | Where it belongs |
| --- | --- | --- | --- | --- |
| JST SH | 1.0 mm | 1 A | friction | tiny sensor breakouts (the Qwiic / STEMMA QT I2C standard uses 4-pin SH) |
| JST GH | 1.25 mm | 1 A | latch | signal harnesses that must survive vibration |
| JST PH | 2.0 mm | 2 A | friction | small batteries, servos, low-current boards |
| JST XH | 2.5 mm | 3 A | friction | balance leads, fans, low-power modules |
| Molex Micro-Fit 3.0 | 3.0 mm | single-digit amps | latch | motor logic power, mid-current rails where a positive lock matters |
| Molex Mini-Fit Jr. | 4.2 mm | around 9 A | latch | main DC distribution inside a chassis |
| XT30 / XT60 / XT90 | bullet | 30 / 60 / 90 A nominal | friction (locking variants exist) | battery to drive bus |
| 2.54 mm header ("Dupont") | 2.54 mm | about 1–3 A | none | prototyping only |

Rules that follow. Anything that carries motor current uses a family with a rating and a lock, never header pins. Give each voltage on the robot its own connector family or at least its own pin count, so a 24 V plug cannot enter a 5 V socket. Prefer a latching family (GH, Micro-Fit) over a friction-fit one (PH, XH) on any cable that moves or sits near a motor. Use the polarised XT or equivalent bullet connectors for battery leads, and buy the anti-spark variant when the bus has large bulk capacitance.

Limits: catalogue ratings assume the manufacturer's contacts and crimp tooling; the many unbranded copies of these families are not covered by the rating. Environmental sealing is a separate specification; none of these families is sealed without a dedicated variant.
