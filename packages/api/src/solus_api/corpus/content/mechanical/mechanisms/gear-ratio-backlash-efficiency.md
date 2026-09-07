+++
title = "Transmissions: ratio, backlash, efficiency by type, and backdrivability"
kind = "principle"
audience = "fundamentals"
applicability = []
derivation = "solus_original"
confidence = 0.75
confidence_basis = "vendor_stated"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:mechanical/bearings_shafts/keyways-set-screws-clamping-hubs"]
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
  { title = "Harmonic Drive gear catalogue — ratio, backlash, and efficiency data", author = "Harmonic Drive LLC", identifier = "", url = "https://www.harmonicdrive.net/" },
  { title = "maxon catalogue — planetary and spur gearhead specifications", author = "maxon", identifier = "", url = "https://www.maxongroup.com/" },
  { title = "Ball and roller screws — catalogue efficiency data", author = "SKF", identifier = "", url = "https://www.skf.com/" },
  { title = "drylin lead screw technology — catalogue", author = "igus", identifier = "", url = "https://www.igus.com/" },
]
+++

A transmission trades speed for torque. A ratio of `N:1` divides output speed by `N` and multiplies torque by `N` times the efficiency. It also multiplies the motor's rotor inertia by `N²` as seen at the output (reflected inertia) — which is why a heavily geared joint feels stiff and a low-ratio joint can be moved by hand.

**Backlash** is the free play between input and output when the direction of torque reverses — the output does not move until the teeth (or belt, or nut) take up the gap. It shows up as a dead band in position control and as hunting around a setpoint; it adds through every stage, and gearbox specs quote it in arc-minutes at the output.

**Efficiency and character by type**, as vendors publish for their products — the exact figure is in the catalogue for the specific unit:

| Type | Typical efficiency per stage | Backlash | Notes |
|------|------------------------------|----------|-------|
| Spur / helical gear pair | high, mid-to-upper 90s % | present; less with higher gear quality | Cheap, simple, noisy |
| Planetary stage | low-to-mid 90s %; small multi-stage gearheads roughly 60–80 % overall | low to moderate | Compact, coaxial |
| Strain-wave (harmonic) | moderate; strongly dependent on ratio, speed, and temperature | essentially zero | High ratios (30:1 and up) in one stage; the arm-joint default |
| Worm | low to moderate, worse at high ratio | moderate | Often self-locking; cheap right-angle drive |
| Timing belt | high, upper 90s % | very low when tensioned | Quiet, spans distance; limited ratio per stage |
| Ball screw | high, around 90 % | low with preloaded nut | Linear; nearly always backdrivable |
| Lead (trapezoidal) screw | low, tens of percent | moderate, wears in | Linear; usually not backdrivable; cheap |

**Backdrivability** is whether the output can turn the input. It depends on efficiency and ratio: a high-ratio, low-efficiency stage (a worm, a lead screw) holds position with the motor off, which is a feature for a gripper or a lift and a hazard for a joint that must be safe to push against. A low-ratio, high-efficiency stage (belt, single planetary) is backdrivable, which compliant and human-safe arms want, at the cost of power to hold a load.

**When a linkage beats a motor.** If a joint only needs a few positions, a four-bar linkage or cam driven by one motor is lighter, cheaper, and more repeatable than a second motor and controller. Add a motor only when a freedom must be *controlled*, not merely *reached*.
