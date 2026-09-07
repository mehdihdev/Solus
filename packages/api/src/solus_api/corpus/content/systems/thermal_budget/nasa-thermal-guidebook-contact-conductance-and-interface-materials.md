+++
title = "Bolted-joint contact conductance and interface materials: measured values, not datasheet ones"
kind = "reference_value"
audience = "reference"
applicability = []
derivation = "facts_extracted"
confidence = 0.8
confidence_basis = "government_published"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:systems/thermal_budget/theta-ja-is-a-test-board-number", "corpus:systems/thermal_budget/nasa-thermal-guidebook-limits-margins-and-the-living-document"]
further_reading = []
corpus_version = "0.2.0"
revised_in = "0.2.0"

[provenance]
source_class = "us_government_work"
source_title = "NASA Passive Thermal Control Engineering Guidebook, Revision 5.1 (Langley Research Center, NESC Passive Thermal TDT)"
source_publisher = "NASA"
source_url = "https://ntrs.nasa.gov/citations/20220006584"
source_locator = "19 December 2024, §4.4 Correlated Contact Conductances (pp. 68–69) and §5.4 Thermal Interface Materials (pp. 125–126)"
source_license = "public-domain-us-gov"
accessed_at = 2026-09-06
attribution = "NASA, NASA Passive Thermal Control Engineering Guidebook 5.1, 19 December 2024, §4.4 Correlated Contact Conductances (pp. 68–69) and §5.4 Thermal Interface Materials (pp. 125–126) (work of the US Government, public use permitted)"
+++

Two sections of NASA's passive thermal guidebook answer the question every enclosure budget
stalls on: how much heat actually crosses a bolted joint. Facts extracted, with their project
provenance as the guidebook gives it:

Correlated contact conductances from flown hardware (values that models were tuned to after
test, so they include real surface finish, flatness, and bolt patterns):

- Metal-to-metal contact between large parts (not chip-to-board), from SAGE III: about 1,000 to
  5,000 W/m²K.
- Avionics boxes edge-bolted with a thermal grease at the interface, from Ares I-X: about 150 to
  600 W/m²K, with the smaller values for the larger boxes (roughly a square foot of contact area
  and up).
- Chips pressed against a pedestal through a thin thermal pad, from early NDL prototypes: about
  2,200 to 2,800 W/m²K.

The spread across those three lines is the point: a factor of thirty separates a well-clamped
metal joint from a big grease-filled bolted box, and geometry and clamping decide where you land.

On interface materials, the guidebook's findings and advice:

- MSFC tested twenty interface fillers in a bolted aluminium joint in vacuum (NASA
  TM-2003-212500). Performance in the bolted joint did not correlate well with the manufacturers'
  published data, so the guidebook recommends characterising critical interfaces by test rather
  than relying on vendor figures.
- Most interface materials are poor conductors compared with metal, so keep them as thin as
  possible; higher-conductivity materials only earn their cost as the gap grows.
- Match the material's rated temperature range to the interface, check electrical conductivity
  (it generally rises with thermal conductivity), and respect contact-pressure limits: indium
  foil, for example, is not suited to pressures above about 400 psi, and many pads specify a
  maximum compression.
- Select board-level components so overheating does not arise; use interface materials as
  mitigation when a part cannot be changed, not as the plan.

How to use these on a robot: a motor driver bolted to an aluminium chassis plate through a
thin pad is closer to the first and third lines than to the second; a controller box held by four
corner screws with a gap filler behaves like the second. Either way, the number in your budget
should come from a measurement on your joint, and these ranges say how wrong a guess can be.
