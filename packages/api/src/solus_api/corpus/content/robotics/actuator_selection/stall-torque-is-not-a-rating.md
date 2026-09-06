+++
title = "Stall torque is a limit you must not sit at, not a rating you can design to"
kind = "pitfall"
audience = "reference"
applicability = []
derivation = "solus_original"
confidence = 0.9
confidence_basis = "vendor_stated"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = [
  "corpus:robotics/actuator_selection/size-from-the-load-not-the-catalogue",
]
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
  { title = "maxon product catalogue, motor data sheets (nominal vs stall torque, thermal data)", author = "maxon", url = "https://www.maxongroup.com/" },
  { title = "DYNAMIXEL e-Manual, performance graphs and stall torque notes", author = "ROBOTIS", url = "https://emanual.robotis.com/" },
  { title = "Harmonic Drive gear efficiency and rating documentation", author = "Harmonic Drive", url = "https://www.harmonicdrive.net/" },
]
+++

The largest torque number on a motor page is almost always stall torque: the torque the motor produces at zero speed with full supply voltage across the winding, which is also the point of maximum current and maximum heating. It tells you where the motor stops turning. It does not tell you what the motor can hold.

The number to design against for anything sustained is the continuous (nominal, rated) torque. That figure is set by how much heat the winding can shed while staying under its insulation temperature, and it is typically a fraction of stall. Because heating rises with the square of current, sitting at twice the continuous torque produces roughly four times the winding losses; the winding warms over seconds to tens of seconds and the housing over minutes, so a motor can look fine on the bench and fail in a long test.

How it usually goes wrong:

- A joint that holds the arm against gravity is sized so the gravity torque falls just under stall. It holds for a while, the winding overheats, and the smart servo shuts down or the brushed motor degrades.
- Gearbox losses are ignored. The output torque is motor torque times ratio times efficiency, and efficiency is per stage, so a three-stage train multiplies three efficiencies. Strain-wave (harmonic) gears have no backlash but their efficiency depends strongly on speed, load, and temperature and can be low at light load or when cold.
- Supply voltage is lower than the datasheet's test voltage, so real stall torque and no-load speed are both lower than printed.

What to check: the torque at the worst-case static pose against the continuous rating with a margin; the peak torque against the peak rating and the cycle-average heating against the continuous rating; and the gearbox efficiency at the actual operating speed and load, not the headline figure.
