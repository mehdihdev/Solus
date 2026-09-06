+++
title = "Interlock versus enable: the pitfalls that make a stop button decorative"
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
related = ["corpus:systems/safety_interlocks/estop-is-a-hardware-chain", "corpus:systems/safety_interlocks/category-performance-level-and-sto-vocabulary"]
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
  { title = "IEC 61800-5-2 Adjustable speed electrical power drive systems — Part 5-2: Safety requirements — Functional", author = "IEC", identifier = "IEC 61800-5-2", url = "https://www.iec.ch/" },
  { title = "PSR safety relay module documentation", author = "Phoenix Contact", identifier = "PSR series", url = "https://www.phoenixcontact.com/" },
]
+++

Two words get confused. An interlock is a device that stops or prevents motion when a condition is violated: the guard door opens, the cover is lifted, the light curtain is broken. An enable is a device a person must actively hold for motion to be permitted at all, such as the three-position switch on a teach pendant; let go and motion stops. Both feed the hardware stop chain.

The pitfalls, and what to check for each:

- The "E-stop" is the driver's EN or SLEEP pin driven from the microcontroller. That is a software convenience, dependent on the firmware running correctly. Check: trace the path from button to actuator power; if it passes through a processor, it is not a stop chain.
- Normally-open stop wiring. A stop that requires a contact to close cannot stop when a wire breaks. Check: every stop, guard, and enable contact is normally closed, in series, and opening any one de-energises the chain.
- The chain removes logic power but leaves motor power, or the reverse. Actuators on the battery keep the last command; alternatively the logic dies and the driver's inputs float. Check: the chain interrupts actuator power directly, or drives a dual-channel STO input on every drive, and the logic stays powered so it can report.
- One general-purpose relay. Contacts can weld shut under an inductive load and the coil has no way to know. Check: use a safety relay with force-guided contacts and a monitored second channel.
- Restart on release. Twisting the button out re-energises the chain and the last velocity command resumes. Check: reset is a separate deliberate action, and firmware clears its command state on any stop.
- Unsafe defaults on power loss. A gravity-loaded joint drops when torque is removed; pneumatics exhaust; a heater latches on. Check: brakes that engage when de-energised on every axis that can fall, valves whose de-energised state is the safe one, and a stated safe state for every actuator.
- Boot-time glitches. Microcontroller pins float or pulse during reset and can briefly enable a driver. Check: pull enable and direction lines to their inactive state with resistors.
- No supervision above the chain. The chain handles the button; nothing handles a host that silently stops sending commands. Check: a heartbeat from the host and a watchdog in the controller command a controlled stop on timeout.

Test the chain on every commissioning, with actuators unloaded: press each button, open each guard, and confirm actuator power actually drops.
