+++
title = "Coasting pumps the bus, braking does not; and the Kelvin path for the shunt"
kind = "pitfall"
audience = "reference"
applicability = []
derivation = "summary"
confidence = 0.9
confidence_basis = "vendor_stated"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:electrical/motor_drive_electrical/regen-into-a-supply-that-cannot-sink", "corpus:electrical/motor_drive_electrical/ti-slvaf66-bulk-capacitors-and-the-48v-ceramic-rule", "corpus:electrical/motor_drive_electrical/microchip-current-sensing-high-side-vs-low-side"]
further_reading = []
corpus_version = "0.2.0"
revised_in = "0.2.0"

[provenance]
source_class = "vendor_documentation"
source_title = "System Design Considerations for High-Power Motor Driver Applications (SLVAF66)"
source_publisher = "Texas Instruments"
source_url = "https://www.ti.com/cn/lit/an/slvaf66/slvaf66.pdf"
source_locator = "June 2021, §7.1 and §7.1.1 (p. 20), §8.1–8.2 (pp. 22–23)"
source_license = "vendor-terms"
accessed_at = 2026-09-06
attribution = "Texas Instruments, SLVAF66, June 2021, §7.1 and §7.1.1 (p. 20), §8.1–8.2 (pp. 22–23)"
+++

Two sections of TI's high-power motor-driver report describe failures that are easy to reproduce
on a robot and easy to prevent once named. In Solus's words:

Coast versus brake. Coasting means switching every high-side and low-side FET off so the phases
float. A motor is an inductive load with a back-EMF, so when it is left to coast the phase
voltage rises above the drain voltage and current flows out of the motor, through the FET body
diodes, into the supply. The bulk capacitors absorb some of that energy, but their voltage rises
as they do, and the note is explicit that this can exceed the gate driver's absolute maximum if
nothing manages it. The same thing happens in miniature during the dead time of every PWM cycle;
it is harmless there only because the interval is short. The practice the note recommends: have
a plan for the energy in the windings, and prefer braking to coasting. Low-side braking turns
all high-side FETs off and all low-side FETs on, so the phases are shorted to ground and the
current circulates and decays there rather than into the bus; current sensing or drain-source
monitoring tells the controller when it has decayed and the brake can release. Active braking
drives the opposite switch pair to oppose the stored current from the supply side. Stepper
drivers know the same idea as slow and fast decay.

The Kelvin path. A Kelvin connection separates the path that carries the current from the path
that senses the voltage, so the measurement excludes the resistance of the current path. On a
motor board the main current runs through the shunt and two dedicated traces run from the
shunt's pads to the current-sense amplifier's inputs. The note's checklist: keep a distinct
current path and a distinct sense path; minimise the length from shunt to sense pins; make the
two sense traces identical in length and width, ideally routed as a differential pair; and follow
the shunt's recommended landing pattern, because the pad geometry is part of the measurement.

Layout in general. Every trace and pad adds parasitic resistance, inductance, and capacitance,
and the note's point about high power is that more current and voltage make the same parasitics
matter more; the primary goal of layout is to shrink them until they are negligible.

On a robot: a motor decelerated by cutting PWM on a supply that cannot sink current (a bench
supply, a protected battery with its BMS open) is the coasting case above; the bus voltage
climbs, and the first thing to fail is usually the driver or the regulator sharing the bus.
