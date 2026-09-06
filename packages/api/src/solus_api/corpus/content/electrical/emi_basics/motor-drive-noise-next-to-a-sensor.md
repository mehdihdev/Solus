+++
title = "Pitfall: a motor drive and a sensitive sensor in the same box — edge rate, coupling paths, and where to fix it"
kind = "pitfall"
audience = "reference"
applicability = []
derivation = "solus_original"
confidence = 0.8
confidence_basis = "vendor_stated"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:electrical/grounding/ground-loops-chassis-vs-signal", "corpus:electrical/grounding/where-return-current-flows"]
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
  { title = "MT-095 EMI, RFI, and Shielding Concepts", author = "Analog Devices", identifier = "MT-095", url = "https://www.analog.com/" },
  { title = "AN-1368 Ferrite Bead Demystified", author = "Analog Devices", identifier = "AN-1368", url = "https://www.analog.com/" },
]
+++

Every interference problem has three parts: a source, a coupling path, and a victim. In a robot the source is almost always a motor drive: a bridge switching tens of amps with edges of tens of nanoseconds. The victims are the IMU, the encoders, the analog sensors, and the radio. Fixing the problem means breaking the path, and the paths come in four kinds.

Conducted: the drive's current pulses flow through a shared supply or ground conductor and the victim sees the resulting voltage drop as signal. Fix at the source and path: bulk capacitance at the drive, separate returns to the battery, no shared ground conductor between drive and sensor.

Capacitive: a fast-changing voltage on a motor phase wire couples through stray capacitance into a nearby high-impedance signal wire. Distance and a grounded shield between them are the fixes; the victim's impedance matters too, so a 10 kΩ sensor line is far more susceptible than a 100 Ω one.

Inductive: the loop formed by motor wires couples magnetically into any loop nearby. Twist the phase wires together so their fields cancel, keep sensor pairs twisted, and keep loop areas small on both sides.

Radiated: at the harmonics of the edge rate, wires and slots become antennas. It is the edge rate, not the PWM frequency, that sets how far up the spectrum the energy goes: a 20 kHz PWM with 20 ns edges has significant content past 10 MHz. Slowing the gate drive slightly (a larger gate resistor) is often the single most effective fix, at the cost of a little switching loss.

Ferrite beads work by being lossy, roughly resistive at high frequency, and they saturate with DC current; a bead on a motor supply line rated below its current does nothing. Analog Devices' AN-1368 explains how to read the impedance curves. Cable shields should be bonded at both ends with a full-circumference connection for high-frequency interference, and at one end only when the concern is a low-frequency ground loop; a shield connected through a pigtail wire is barely a shield. MT-095 sets out the shielding trade-offs.

Check first: does the fault appear only when the motors run, and does it change when a sensor cable is re-routed? That answers source and path before any component is changed.
