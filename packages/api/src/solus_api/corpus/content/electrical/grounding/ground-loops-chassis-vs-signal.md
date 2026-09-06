+++
title = "Pitfall: ground loops through chassis, connector shells, and mounting hardware"
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
related = ["corpus:electrical/grounding/where-return-current-flows"]
further_reading = [
  { title = "Electromagnetic Compatibility Engineering", author = "Ott", identifier = "ISBN 978-0470189306" },
]
corpus_version = "0.1.0"
revised_in = "0.1.0"

[provenance]
source_class = "solus_authored"
source_title = "Solus engineering corpus"
source_publisher = "Solus"
source_license = "solus-proprietary"
accessed_at = 2026-09-06
checked_against = [
  { title = "MT-031 Grounding Data Converters and Solving the Mystery of AGND and DGND", author = "Analog Devices", identifier = "MT-031", url = "https://www.analog.com/" },
  { title = "MT-095 EMI, RFI, and Shielding Concepts", author = "Analog Devices", identifier = "MT-095", url = "https://www.analog.com/" },
]
+++

A ground loop forms whenever two subsystems are connected to "ground" by more than one path: the intended return wire plus a connector shell, a shielded cable, a metal standoff into the chassis, or a USB cable to a laptop that is also plugged into the same bench supply. Current then divides between the paths according to their impedance, and some of it flows through the conductor a sensitive circuit is using as its voltage reference. The reference shifts by that current times the path's impedance, and the circuit reads the shift as signal.

In a robot the symptoms are recognisable: an analog sensor whose reading jumps when the drive motors start; encoder counts that glitch under load; a serial link that throws framing errors only when the arm moves; audible hum in a microphone; an IMU whose bias depends on whether the debug USB cable is attached. The common cause is a motor or regulator return that has found a second path through the signal ground.

Two grounds need to be kept distinct in the design vocabulary. Chassis ground is the enclosure and frame: it is a safety and EMI reference, and it should be bonded to the electrical ground at one deliberate point. Signal ground is the reference the measurements are made against. When mounting screws, connector shells, and cable shields each connect the two at a different place, the frame becomes a parallel return conductor for whatever current happens to be flowing.

What to check: with the robot powered and motors running, measure the voltage between the "grounds" of two boards, and between a board ground and the frame; anything more than a few millivolts is a loop carrying current. Bond chassis to electrical ground at one point, insulate standoffs elsewhere, terminate cable shields at one end for low-frequency signals, and use differential or isolated links (CAN, RS-485, isolated serial) where two subsystems are far apart or share heavy currents. Analog Devices' MT-031 and MT-095 cover the mixed-signal and shielding sides.
