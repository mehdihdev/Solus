+++
title = "Every cross-domain interface needs one owner and one written definition"
kind = "principle"
audience = "fundamentals"
applicability = []
derivation = "solus_original"
confidence = 0.85
confidence_basis = "government_published"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:systems/system_integration/commissioning-order", "corpus:systems/system_integration/cross-domain-changes-that-break-the-other-team"]
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
  { title = "NASA Systems Engineering Handbook (interface management)", author = "NASA", identifier = "NASA/SP-2016-6105 Rev 2", url = "https://www.nasa.gov/" },
  { title = "NASA Systems Engineering Processes and Requirements", author = "NASA", identifier = "NPR 7123.1", url = "https://www.nasa.gov/" },
]
+++

Robots rarely fail inside a domain. The firmware works, the board works, the bracket fits its drawing, and the robot still does not move, because the pin the firmware toggles is not the pin the board routed to the driver, or the connector the harness was built for is mirrored relative to the one the CAD placed. The failures live at the interfaces, and interfaces are the one thing nobody in a domain-specific tool is looking at.

Systems engineering practice answers this with interface control: for every boundary between two parts of the system, a written definition of what crosses it and a named owner who is the only one allowed to change it. Aerospace programmes formalise this as an interface control document; a small robotics team needs the same discipline with far less ceremony. The definition for one interface is short: the connector part number and its keying, each pin with its signal name, direction, voltage level and current, the protocol and its version, the units and sign convention of any quantity carried, the coordinate frame if it is a mechanical or sensor interface, and the mounting pattern and envelope if it is a physical one.

The owner is whoever's artefact is the source of truth for that item. The schematic owns which signal is on which pin; the firmware pin map is a consumer of the schematic and must be checked against it, not the other way around. The CAD owns the connector's position and orientation; the harness drawing consumes it. The ROS message definition owns the units and frame of a published quantity; the firmware that fills it consumes that definition. When the owner changes an owned item, every consumer is notified before the change lands, and the consumers confirm they have updated or object.

| Interface item | Owner (source of truth) | Consumers who must be told |
| --- | --- | --- |
| Pin-to-signal assignment on J3 | schematic | firmware pin map, harness drawing |
| J3 location and orientation on the enclosure | CAD assembly | harness length, PCB outline |
| Wheel odometry units and sign | ROS message definition | firmware publisher, navigation stack |
| Supply rail voltage | power architecture | every board, every actuator, the battery |

This is also what Solus's graph is for: entities for the connector, the pins, the signals, and the parts on each side, with typed relations recording who consumes what, so a change on one side surfaces the consumers on the other before the robot finds them.
