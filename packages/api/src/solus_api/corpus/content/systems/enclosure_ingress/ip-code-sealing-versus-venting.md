+++
title = "IP codes, sealing versus venting, and why sealed boxes fill with water"
kind = "principle"
audience = "fundamentals"
applicability = [{ key = "environment", value = "wet" }]
derivation = "solus_original"
confidence = 0.8
confidence_basis = "standard_derived"
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
  { title = "IEC 60529 Degrees of protection provided by enclosures (IP Code)", author = "IEC", identifier = "IEC 60529", url = "https://www.iec.ch/" },
  { title = "NEMA 250 Enclosures for Electrical Equipment (1000 Volts Maximum)", author = "NEMA", identifier = "NEMA 250", url = "https://www.nema.org/" },
  { title = "Cable gland product documentation", author = "Phoenix Contact", identifier = "cable gland catalogue", url = "https://www.phoenixcontact.com/" },
]
+++

An IP code from IEC 60529 has two digits. The first grades protection against solid objects and dust, the second against water; an X in either place means that axis was not tested, not that it passed. The digits are the names of defined test conditions, so a rating describes how the enclosure behaved in that test, as tested, with its cable entries as tested. It is not a general promise about the field. Two things follow. Every hole you add afterwards, for a cable, a switch, or a vent, re-rates the enclosure to whatever that hole achieves. And the water digits are not a simple ladder: the tests for temporary immersion and for pressurised jets are different tests, so an enclosure rated for immersion has not automatically been shown to resist a jet, which is why some products carry both ratings. NEMA 250 is the North American enclosure vocabulary that covers similar ground with a different scheme; the two are not directly convertible.

Sealing is not the same as keeping water out. A sealed box breathes anyway: its air warms while the robot runs and cools when it stops, and every cycle pushes air out through the weakest gasket and then pulls outside air, with its moisture, back in. The moisture condenses on the coldest inner surface and has no way out. This is how a "waterproof" enclosure ends up with a puddle in it after a season of dry weather. The design options are to equalise pressure deliberately with a membrane vent that passes air and vapour but not liquid water, to provide a drain at the lowest point so any water that gets in leaves, or to remove the air volume entirely by potting the electronics. Condensation also happens the other way: a cold robot brought into warm humid air fogs inside within minutes, so allow it to warm before power-up or design so condensation lands somewhere harmless.

Cable entries are where most enclosures actually leak. A cable gland seals only when its sealing range matches the cable's outer diameter and the cable is round; a flat cable or two cables through one gland does not seal. Glands also provide strain relief so pulling on the cable does not pull on the connection inside. Put entries on the bottom or side, never the top, and leave a drip loop so water runs off the cable before it reaches the gland. Sealed connectors are rated when mated; an unmated receptacle needs a cap. On the board, a conformal coating protects against condensation but not against immersion, and it must be kept off connectors and test points.
