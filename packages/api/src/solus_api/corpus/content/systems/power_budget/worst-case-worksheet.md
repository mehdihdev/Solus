+++
title = "Build the power budget from datasheet worst cases, not typicals"
kind = "procedure"
audience = "fundamentals"
applicability = []
derivation = "solus_original"
confidence = 0.9
confidence_basis = "consensus"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:systems/power_budget/peak-sizes-the-regulator-average-sizes-the-battery", "corpus:systems/power_budget/servo-browns-out-the-5v-rail"]
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
  { title = "NASA Systems Engineering Handbook (technical margins and resource budgets)", author = "NASA", identifier = "NASA/SP-2016-6105 Rev 2", url = "https://www.nasa.gov/" },
  { title = "Gearmotor product documentation stating free-run and stall current", author = "Pololu", identifier = "product pages", url = "https://www.pololu.com/" },
  { title = "Raspberry Pi documentation: power supply requirements", author = "Raspberry Pi Ltd", identifier = "Raspberry Pi hardware documentation", url = "https://www.raspberrypi.com/" },
]
+++

A power budget is one table per rail: every load, the largest current it can draw under a condition that can really occur, which of those conditions can occur at the same time, the sum, a margin, and the source's guaranteed capability under the same conditions. Most budget failures are not arithmetic errors; they are the wrong number in a cell.

Take the worst-case column from the datasheet, not the typical. "Typical" is a characterisation at room temperature on the vendor's evaluation board. "Maximum" is what the vendor will stand behind across temperature and process spread. For anything with a motor, the sizing number is stall current (or the driver's current limit, if the driver enforces one), because a motor at standstill draws close to its stall current until it spins up. For a radio, use the transmit burst. For a compute module, use the vendor's stated supply requirement rather than a measured idle. For a hobby servo, use the current it draws when starting under load or held against a stop.

A worksheet that forces the right question in each cell:

| Load | Rail | Typical (A) | Worst case (A) | Condition for worst case | Can coincide with | Duty |
| --- | --- | --- | --- | --- | --- | --- |
| Drive motor L | 24 V | 1.2 | 9.5 | stall / start | drive motor R, radio TX | brief |
| Compute module | 5 V | 1.5 | 3.0 | boot, all cores + USB | everything | continuous |

Sum the worst-case column only across loads that can coincide, and treat "I cannot prove they never coincide" as "they coincide". Then add margin. Systems-engineering practice treats margin as a managed resource: generous early, when parts are still changing, tightened as measurements replace estimates, never zero at release.

Compare the sum against the source as it actually is: battery voltage near end of discharge under load, regulator output current at the enclosure's internal temperature rather than at 25 degrees Celsius, and the rating of every wire and connector on the path. Check the voltage at the load's terminals after cable drop, not at the regulator. The same table answers two different questions: the worst-case sum sizes the regulator, wiring, and connectors; the duty-weighted average sizes battery energy and thermal dissipation.
