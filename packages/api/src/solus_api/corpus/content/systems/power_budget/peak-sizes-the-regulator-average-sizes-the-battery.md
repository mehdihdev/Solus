+++
title = "Peak current sizes the regulator and wiring; average sizes the battery"
kind = "rule_of_thumb"
audience = "reference"
applicability = []
derivation = "solus_original"
confidence = 0.8
confidence_basis = "rule_of_thumb"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:systems/power_budget/worst-case-worksheet"]
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
  { title = "Basic Calculation of a Buck Converter's Power Stage", author = "Texas Instruments", identifier = "SLVA477", url = "https://www.ti.com/" },
  { title = "Gearmotor product documentation stating free-run and stall current", author = "Pololu", identifier = "product pages", url = "https://www.pololu.com/" },
  { title = "DYNAMIXEL e-Manual: actuator electrical specifications", author = "ROBOTIS", identifier = "e-Manual", url = "https://www.robotis.com/" },
]
+++

Two numbers come out of one power budget and they size different things.

Peak current sizes the regulator, the wiring, the connectors, and the protection. A brushed motor at standstill has no back-EMF, so its current is limited only by winding resistance and whatever the driver clamps it to; vendors publish this as stall current, and on small gearmotors it is commonly several times to an order of magnitude above the free-run current. Read the vendor's stall figure; do not estimate it from the rated figure. Starting a motor from rest, reversing it, or stalling it against a load all reach toward that number for at least tens of milliseconds. A regulator whose current limit is below the peak folds back or shuts down, and the rail dips for every load sharing it.

Average current sizes the battery's energy and the steady-state thermal load. Duty-weight each load and sum. Battery capacity in ampere-hours is stated at a particular discharge rate and temperature; capacity falls at high discharge rates and in the cold, so a pack sized on nameplate capacity for a robot that runs outdoors in winter will come up short.

Rules of thumb, with their limits:

- Run regulators, batteries, and connectors at a comfortable fraction of their rated continuous current for the steady-state case; a widely used engineering practice is to leave roughly a fifth of the rating unused. This is a starting point for margin, not a substitute for the thermal calculation at your enclosure's internal temperature.
- Peak sag matters more than average sag. A battery's voltage under a motor-start spike is its open-circuit voltage minus the spike current times its internal resistance plus the cable resistance. If that dip reaches a regulator's minimum input voltage, or a BMS low-voltage cutoff, the robot resets or shuts down even though the average current was fine.
- A regulator's datasheet output current is typically stated at room temperature on an evaluation board with generous copper. Expect less at the enclosure's real internal temperature; the derating curve, not the headline, is the number to budget against.
- A servo or stepper that is holding position is still drawing current, sometimes near its maximum. "Not moving" is not "not loaded".
