+++
title = "Every signal is a loop: return current follows the lowest-impedance path, not the shortest wire"
kind = "principle"
audience = "fundamentals"
applicability = []
derivation = "solus_original"
confidence = 0.9
confidence_basis = "vendor_stated"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:electrical/grounding/star-vs-plane-and-mixed-signal", "corpus:electrical/grounding/ground-loops-chassis-vs-signal"]
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
  { title = "PCB Design Guidelines for Reduced EMI", author = "Texas Instruments", identifier = "SZZA009", url = "https://www.ti.com/" },
  { title = "MT-031 Grounding Data Converters and Solving the Mystery of AGND and DGND", author = "Analog Devices", identifier = "MT-031", url = "https://www.analog.com/" },
]
+++

There is no such thing as a one-wire signal. Every current that leaves a driver has to come back to it, and the path it takes back is as much a part of the circuit as the trace you drew. "Ground" is just the name we give to the conductor we hope the return uses.

At DC and low frequencies the return spreads out across whatever copper is available, following the least resistance. As frequency rises, inductance takes over: the return current concentrates directly underneath the signal trace, because that path encloses the smallest loop and therefore has the lowest inductance. The transition happens at surprisingly low frequencies, well below a megahertz for typical board geometry, and a digital edge with a few nanoseconds of rise time contains energy far above that.

Three things follow. A ground plane works because it always offers a return directly under any trace, so loops stay small without the designer thinking about each one. A slot, a split, or a row of vias that cuts the plane under a trace forces the return to detour around the obstruction, which enlarges the loop, raises the impedance the signal sees, and turns the loop into an antenna. And the potential of the "ground" is not the same everywhere: a return current flowing through plane impedance creates a voltage difference between two points on it, which is exactly what one circuit's reference sees as noise from another's.

For a robotics engineer coming from software or mechanical work, the mental model is: draw the return path for every signal and every power current, imagine it as a wire, and ask what else shares that wire. Motor currents, switching-regulator currents, and sensor references should not share a return conductor. TI's SZZA009 and Analog Devices' MT-031 set this out for digital and mixed-signal boards respectively.
