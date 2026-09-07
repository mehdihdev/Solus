+++
title = "The cross-domain changes that silently break another team"
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
related = ["corpus:systems/system_integration/interface-control-who-owns-a-pin", "corpus:systems/system_integration/commissioning-order"]
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
  { title = "NASA Systems Engineering Handbook (interface management and configuration management)", author = "NASA", identifier = "NASA/SP-2016-6105 Rev 2", url = "https://www.nasa.gov/" },
  { title = "REP 103 Standard Units of Measure and Coordinate Conventions", author = "Open Robotics", identifier = "REP 103", url = "https://www.ros.org/" },
]
+++

Each of these is a change that looks local to the person making it and is invisible to the person it breaks. Each has a check that catches it before the robot does.

| Change made in one domain | What silently breaks elsewhere | Check |
| --- | --- | --- |
| Two signals swapped on a connector in the schematic | Firmware pin map and the built harness still use the old assignment | Diff pin assignments against the firmware pin map and harness drawing on every schematic change |
| Connector drawn from the mating face instead of the wire face | Harness built mirrored; pin 1 lands on the far side | State the viewing side on every pinout; verify pin 1 to pin 1 with a meter before power |
| Mounting holes or board outline moved in CAD after boards were ordered | Board no longer fits, or a standoff shorts a trace | Export the PCB outline and hole pattern from the CAD source and diff it against the fabricated board |
| Enclosure wall moved closer to a port | Cable no longer clears its minimum bend radius, or the connector cannot mate | Model the mated connector and cable exit in CAD, not just the receptacle |
| Motor leads rewired or encoder connector re-pinned | Direction or encoder sign inverts; position loop runs away | Re-run the direction and encoder-sign step of commissioning before closing any loop |
| Units or frame convention changed in a message or config | Downstream consumers read metres as millimetres, or x as y | Follow one convention (REP 103 in ROS) and record units and frame in the message definition itself |
| Baud rate or protocol version changed in firmware | Host driver still speaks the old version; symptoms look like a bad cable | Version the protocol and reject mismatched versions loudly at connect |
| Supply rail raised | A peripheral rated for the old rail is destroyed at first power-up | List every consumer of the rail in the interface record and confirm each rating |
| Mass or centre of mass changed in CAD | Actuator sizing and the simulation model are no longer valid; the arm sags or trips a current limit | Re-export mass properties to the URDF and re-check actuator torque margin |

The common thread: the person making the change owns one artefact and cannot see its consumers. The fix is an interface record that lists them and a habit of notifying them before the change lands; this is the failure class Solus exists to catch.
