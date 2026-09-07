+++
title = "An emergency stop is a hardware chain that removes power, never a software command"
kind = "principle"
audience = "fundamentals"
applicability = []
derivation = "solus_original"
confidence = 0.9
confidence_basis = "standard_derived"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:systems/safety_interlocks/category-performance-level-and-sto-vocabulary", "corpus:systems/safety_interlocks/interlock-vs-enable-pitfalls"]
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
  { title = "ISO 13850 Safety of machinery — Emergency stop function — Principles for design", author = "ISO", identifier = "ISO 13850", url = "https://www.iso.org/" },
  { title = "IEC 60204-1 Safety of machinery — Electrical equipment of machines — Part 1: General requirements", author = "IEC", identifier = "IEC 60204-1", url = "https://www.iec.ch/" },
  { title = "PSR safety relay module documentation", author = "Phoenix Contact", identifier = "PSR series", url = "https://www.phoenixcontact.com/" },
]
+++

An emergency stop works when everything else has already failed: the firmware has hung, the host has lost the link, the motor driver is executing the last command it received. So the stop cannot depend on any of those things. It is a hardware chain.

The chain is a loop of normally-closed contacts in series: every E-stop button, every guard switch, every pull-cord. While all contacts are closed, the loop holds a contactor or a safety relay energised, and that device is what connects power to the actuators. Pressing any button opens the loop, the coil de-energises, the contacts drop out, and actuator power is gone. Nothing in that path is a processor.

This shape is what makes it fail-safe. A broken wire, an unplugged connector, a corroded contact, or a dead control battery all open the loop and look exactly like a pressed button: the robot stops. Compare the opposite design, a normally-open button that must conduct to signal "stop": every one of those faults makes the stop silently impossible. The principle is that removing energy must be the safe state, and that the stop must be what happens when the chain is broken, not what happens when a message arrives.

An E-stop button latches. Once pressed it stays pressed until someone deliberately twists or pulls it, and releasing it must not by itself restart anything. Reset is a separate, intentional action, and the software must not resume motion from where it left off just because power came back.

Software still has a role, but as a second layer above the chain, not as the chain. A host heartbeat, a watchdog in the controller, and a controlled ramp-down commanded before the contactor opens all reduce wear and make the stop less violent. The vocabulary for the choice between cutting power immediately and commanding a controlled stop first comes from IEC 60204-1 on the electrical equipment of machines, which names distinct stop categories; ISO 13850 covers the design principles of the emergency stop function itself. Solus explains these terms; deciding what a specific machine requires is a risk assessment done by a qualified person, and nothing in this corpus is a statement that a design complies with either standard.

For a small robot the chain can be as simple as one button, one safety relay with force-guided contacts, and a contactor on the motor battery lead. It still must not run through the microcontroller.
