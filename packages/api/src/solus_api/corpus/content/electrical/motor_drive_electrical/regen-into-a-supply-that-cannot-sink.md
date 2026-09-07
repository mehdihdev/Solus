+++
title = "Pitfall: regenerative braking into a supply that cannot absorb current"
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
related = ["corpus:electrical/power_design/inrush-brownout-reverse-polarity-hotplug"]
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
  { title = "ODrive documentation — brake resistor and DC bus overvoltage", author = "ODrive Robotics", identifier = "", url = "https://docs.odriverobotics.com/" },
  { title = "Basic Calculation of a Buck Converter's Power Stage", author = "Texas Instruments", identifier = "SLVA477", url = "https://www.ti.com/" },
]
+++

A motor decelerating under control is a generator. The drive's bridge, which is just a set of switches, passes the current it produces straight back onto the DC bus, and the energy has to go somewhere. If the bus is a battery, the battery absorbs it (within its charge-current limit and as long as its protector does not open). If the bus is a bench supply, a buck converter, or a battery whose BMS has just disconnected for overcharge, nothing can sink the current, the bus capacitors charge, and the bus voltage climbs until something fails: the drive's overvoltage protection trips and the motor coasts, or a capacitor or FET exceeds its rating.

This is the commonest way a robot that ran perfectly on a battery destroys its drive on the bench, and the commonest cause of "overvoltage fault when stopping".

The energy is the kinetic energy of the load plus whatever the motor's inductance holds, so heavy wheels stopping quickly and arms lowering a payload are the worst cases. Reducing deceleration or lowering payload only postpones the issue.

Fixes, in the order to try them:

- A brake resistor with a chopper: the drive switches a resistor across the bus when voltage exceeds a threshold and burns the energy as heat. Many robot motor controllers have the terminals and the logic for this; the ODrive documentation is one accessible description of the mechanism.
- Enough bus capacitance to absorb the expected energy with acceptable voltage rise, which is the right answer only for small loads (the energy grows with the square of speed, capacitance requirements follow).
- A supply that can sink, or a battery in the loop even when a supply is present.
- Limiting braking current in the drive's configuration so the regenerated power stays within what the bus can absorb.

Do not rely on a transient-voltage-suppressor diode as the primary absorber; it is sized for microsecond transients, not for the joules of a stopping wheel, and it will fail short.

Check: the drive's overvoltage threshold against the supply voltage plus expected rise; whether the supply is a battery, a converter, or a bench unit; and the BMS behaviour on charge-current excursions.
