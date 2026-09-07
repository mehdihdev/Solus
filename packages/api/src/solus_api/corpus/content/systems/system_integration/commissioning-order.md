+++
title = "Commission a robot in layers: stop chain, power, communications, then one actuator at a time"
kind = "procedure"
audience = "fundamentals"
applicability = []
derivation = "solus_original"
confidence = 0.85
confidence_basis = "consensus"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:systems/system_integration/interface-control-who-owns-a-pin", "corpus:systems/safety_interlocks/estop-is-a-hardware-chain"]
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
  { title = "NASA Systems Engineering Handbook (product integration and verification)", author = "NASA", identifier = "NASA/SP-2016-6105 Rev 2", url = "https://www.nasa.gov/" },
  { title = "DYNAMIXEL e-Manual: initial setup and ID assignment", author = "ROBOTIS", identifier = "e-Manual", url = "https://www.robotis.com/" },
]
+++

Powering a freshly assembled robot with everything connected and hoping is the most expensive test you can run, because when something fails you have no idea which of fifty things it was. Commission in layers, so each layer is proven before the next one can hurt it.

1. Cold checks, nothing powered. Inspect polarity at every power connector against the interface record. With a meter, check each rail for a short to ground and check that no two rails are shorted together. Confirm every connector is keyed and seated. Put the robot in a state where nothing can move dangerously: wheels off the ground, arm in a supported pose, blades removed.
2. Prove the stop chain first, with actuator power disconnected downstream of the contactor. Press each button and open each guard; confirm the contactor drops out every time.
3. Power the rails with the loads disconnected. Measure each rail at the regulator and at the far end of the harness. Then connect loads one group at a time, watching the supply current against the power budget; a group that draws far more than its worst-case line is wired wrong or damaged.
4. Bring up communications with actuators still unpowered. Enumerate each bus: addresses, node IDs, baud rates, termination. Multi-drop servo buses in particular ship every unit with the same default ID, and two identical IDs on one bus produce silence rather than an error, so assign and verify IDs one device at a time.
5. Read every sensor and check sign and frame conventions against the interface record. Tilt the IMU by hand and confirm the axis that changes is the one the message definition says. Turn a wheel forward by hand and confirm the encoder counts up.
6. Power actuators one at a time, unloaded, with the driver's current limit set low and speed commands small. Confirm direction matches the command and that the encoder sign agrees with the motion before any control loop is closed. A position loop with an inverted encoder runs away at full torque; this step is what prevents it.
7. Close loops at low gains, one axis at a time, then raise gains and add load.
8. Run the integrated system and record baseline currents, rail voltages, and case temperatures under representative duty. That baseline is what tells you, months later, that something has changed.

Every step has a pass condition written down before you start, and a failed step stops the sequence. The order exists so that the layer that could hurt you is never the one under test.
