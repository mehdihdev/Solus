+++
title = "Star ground for low-frequency current separation, a solid plane for everything with edges"
kind = "rule_of_thumb"
audience = "reference"
applicability = []
derivation = "solus_original"
confidence = 0.85
confidence_basis = "vendor_stated"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:electrical/grounding/where-return-current-flows"]
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
  { title = "MT-031 Grounding Data Converters and Solving the Mystery of AGND and DGND", author = "Analog Devices", identifier = "MT-031", url = "https://www.analog.com/" },
  { title = "Grounding in mixed-signal systems demystified", author = "Texas Instruments", identifier = "", url = "https://www.ti.com/" },
]
+++

Star grounding brings each subsystem's return to a single point on its own conductor, so that no return current flows through another subsystem's reference. It works when the currents are slow enough that resistance, not inductance, dominates, and it is the right tool at the system level: motor drivers, battery, and the logic board should each have their own return to the pack negative or a single bus bar rather than daisy-chaining through one another. Its weakness is that long separate returns form large loops, and for anything with fast edges a large loop is a large inductance and a large antenna.

A solid ground plane does the opposite. It gives every signal a return directly beneath it, so loops are small automatically. For any PCB carrying digital logic, switching regulators, or high-speed buses, one unbroken plane is the default, and cutting it up to "separate" grounds usually makes things worse.

Mixed-signal boards combine the two ideas by placement, not by slicing the plane. Put the analog parts, their references, and the ADC's analog side in one region of the board and the digital parts in another; route digital signals only over the digital region and analog signals only over the analog region. The return currents then stay under their own signals and the two regions barely interact, even though the plane is continuous. Analog Devices' MT-031 recommends connecting a converter's AGND and DGND pins together at the device to the analog ground region, since those pins name the die's internal references, not where the return should flow.

Split planes are justified only when you can draw every return path and prove nothing crosses the split; if a single trace crosses it, its return must detour around the gap and you have built a slot antenna. When in doubt: one plane, deliberate placement, and star topology only for the heavy DC returns in the harness.
