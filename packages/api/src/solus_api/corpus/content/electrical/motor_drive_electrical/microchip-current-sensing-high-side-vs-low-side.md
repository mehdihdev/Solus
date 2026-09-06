+++
title = "Motor current sensing: high side, low side, and what each costs"
kind = "principle"
audience = "fundamentals"
applicability = []
derivation = "summary"
confidence = 0.9
confidence_basis = "vendor_stated"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:electrical/motor_drive_electrical/regen-into-a-supply-that-cannot-sink", "corpus:electrical/analog_frontend/op-amp-supply-rails-and-headroom"]
further_reading = []
corpus_version = "0.2.0"
revised_in = "0.2.0"

[provenance]
source_class = "vendor_documentation"
source_title = "DC Motor Control Tips 'n Tricks, Chapter 5 (Tips #1 and #6)"
source_publisher = "Microchip Technology"
source_url = "https://ww1.microchip.com/downloads/aemDocuments/documents/OTH/ProductDocuments/SupportingCollateral/chapter5.pdf"
source_locator = "2008, pp. 5-2 and 5-8"
source_license = "vendor-terms"
accessed_at = 2026-09-06
attribution = "Microchip Technology, DC Motor Control Tips 'n Tricks, 2008, pp. 5-2 and 5-8"
+++

Microchip's motor-control tips booklet states two things every brushed-DC drive needs to get
right. Restated in Solus's words:

Torque is proportional to current, so measuring current is how you measure and limit torque.
The measurement is made either by the voltage across a known resistor in the motor path or by
the magnetic field of a known inductor (a Hall or magnetic sensor). Resistive sensing is the
common case on a small robot.

Where you put the resistor decides the amplifier you need. Low-side sensing puts the resistor
between the drive's return and ground: the signal is ground-referenced, a single-ended
amplifier or even a direct ADC input works, and it is the simpler circuit. Its cost is that the
motor is no longer at ground potential, which the note flags as a safety problem in some
applications and which also means a short from a motor lead to chassis bypasses the sense
resistor entirely. High-side sensing puts the resistor between the supply and the bridge: the
motor stays grounded and every fault current is seen, but the amplifier must handle a
common-mode voltage at the supply rail, so it is a differential or dedicated high-side
current-sense amplifier rather than an op-amp at logic supply.

The H-bridge is the only solid-state way to run a brushed motor in both directions; the note's
four-switch figure is the shape every integrated driver reproduces. A single high-side or
low-side switch gives one direction only.

What the note does not say and the corpus adds as a pointer: in an H-bridge the low-side shunt
sees the motor current only while a low-side switch conducts, so the ADC sample must be timed to
the PWM, and the shunt's own inductance plus a long trace to the amplifier turns each switching
edge into a spike. The Kelvin-connection guidance in the trace-width chunks applies to the sense
resistor here too.

Applicability: any brushed or stepper driver; for a BLDC the same trade-off appears as phase
shunts versus a single DC-link shunt, which the TI high-power motor-drive chunk covers.
