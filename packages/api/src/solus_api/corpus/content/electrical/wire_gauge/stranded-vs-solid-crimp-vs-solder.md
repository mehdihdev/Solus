+++
title = "Pitfall: solid wire on moving parts, soldered joints where a crimp belongs"
kind = "pitfall"
audience = "reference"
applicability = []
derivation = "solus_original"
confidence = 0.9
confidence_basis = "government_published"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:electrical/wire_gauge/awg-vs-mm2-and-what-limits-a-wire", "corpus:electrical/connector_selection/connector-pitfalls"]
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
  { title = "NASA-STD-8739.4 Workmanship Standard for Crimping, Interconnecting Cables, Harnesses, and Wiring", author = "NASA", identifier = "NASA-STD-8739.4", url = "https://standards.nasa.gov/" },
  { title = "IPC/WHMA-A-620 Requirements and Acceptance for Cable and Wire Harness Assemblies", author = "IPC", identifier = "IPC/WHMA-A-620", url = "https://www.ipc.org/" },
  { title = "Quality Crimping Handbook", author = "Molex", identifier = "", url = "https://www.molex.com/" },
]
+++

Solid wire is for things that never move: building wiring, breadboards, a jumper soldered flat to a board. Bend it repeatedly, or let a motor vibrate it against a clamp, and it work-hardens and cracks at the point of flexure. Anything in a robot harness that crosses a joint, runs to a wheel module, or simply lives on a chassis that shakes should be stranded. Where the cable flexes continuously, choose a high strand count with silicone or similar flexible insulation; a few large strands fatigue almost as fast as a solid conductor.

Crimping versus soldering is the second recurring argument, and the workmanship standards (NASA-STD-8739.4, IPC/WHMA-A-620) settle it: a correctly made crimp is the preferred wire termination for harnesses. The terminal is cold-formed around the strands with enough pressure to produce a gas-tight, metallurgically bonded joint that neither corrodes internally nor loosens, and the terminal's insulation grip or the connector housing provides strain relief. "Correctly made" means the manufacturer's tool for that terminal series, a terminal sized for the wire gauge, the specified strip length, no insulation inside the conductor barrel, and a pull-test on a sample.

Solder on a stranded wire wicks along the strands and turns the flexible conductor into a rigid one for several millimetres. The boundary between the stiff soldered section and the still-flexible wire is where the strands fracture under vibration. That is why the standards do not allow soldering a crimped joint afterwards, and why tinning wire ends that go into screw terminals is discouraged: the solder creeps under clamping pressure and the joint loosens. Use a crimp ferrule instead.

What to check on a failing harness: pliers-crimped terminals (the barrel is squashed, not formed), strands visible outside the barrel, insulation in the barrel, wire gauge smaller than the terminal's range, and any soldered joint that is also expected to flex. Fix by re-terminating with the right tool, and add a service loop and a clamp so the crimp carries no mechanical load.
