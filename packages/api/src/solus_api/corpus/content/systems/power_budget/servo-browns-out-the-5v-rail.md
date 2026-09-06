+++
title = "How a servo browns out a shared 5 V rail and resets the controller"
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
related = ["corpus:systems/power_budget/worst-case-worksheet", "corpus:systems/power_budget/peak-sizes-the-regulator-average-sizes-the-battery"]
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
  { title = "Raspberry Pi documentation: power supply requirements and under-voltage warning", author = "Raspberry Pi Ltd", identifier = "Raspberry Pi hardware documentation", url = "https://www.raspberrypi.com/" },
  { title = "DYNAMIXEL e-Manual: recommended supply and stall current", author = "ROBOTIS", identifier = "e-Manual", url = "https://www.robotis.com/" },
  { title = "Basic Calculation of a Buck Converter's Power Stage", author = "Texas Instruments", identifier = "SLVA477", url = "https://www.ti.com/" },
]
+++

The symptom: the controller resets, the single-board computer logs an under-voltage warning, or a sensor drops off the bus at exactly the moment a servo starts to move. The average current was well inside the budget. The mechanism is a peak, not an average.

When a servo starts against a load or is driven into a stop, it draws a current spike far above its idle current for tens of milliseconds. If the servo shares a 5 V rail with the microcontroller or compute module, three things conspire: the regulator has a finite current limit and a finite loop response, so its output dips before it recovers; the wiring between regulator and loads has resistance, so the dip at the far end is larger than at the regulator; and the logic's brown-out detector or the compute module's under-voltage monitor trips on a dip lasting only milliseconds. A multimeter averages the event away, which is why "the rail measures 5.02 V" and "the board keeps resetting" are both true. Compute modules such as the Raspberry Pi document a specific under-voltage threshold below which they warn and throttle; check the vendor documentation for the exact figure for your board.

What to check and what to change:

- Look at the rail with an oscilloscope at the controller's supply pin, triggered on the servo command. A dip of a few hundred millivolts is enough.
- Give actuators their own regulator, or their own rail directly from the battery, and keep the logic regulator's input upstream of the actuator drop.
- Add bulk capacitance at the servo end of the wiring, close to the servo connector, so the first milliseconds of the spike come from the capacitor rather than from the shared regulator.
- Wire returns as a star. If the servo's return current shares a ground conductor with the logic, the drop across that conductor appears as a shift in the logic's ground reference.
- Development boards fed from a laptop USB port are limited by the port; the port's current limit is the real budget for anything powered through the board.
- Budget the servo at its start or stall current, with the compute module at its boot-time maximum, as coincident loads. They are.
