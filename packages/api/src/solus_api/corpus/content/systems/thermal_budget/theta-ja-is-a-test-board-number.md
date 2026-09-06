+++
title = "θJA is a test-board number; it does not predict your enclosure"
kind = "pitfall"
audience = "reference"
applicability = []
derivation = "solus_original"
confidence = 0.9
confidence_basis = "vendor_stated"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:systems/thermal_budget/junction-to-ambient-chain"]
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
  { title = "Semiconductor and IC Package Thermal Metrics", author = "Texas Instruments", identifier = "SPRA953", url = "https://www.ti.com/" },
  { title = "JESD51 series: methodology for thermal measurement of component packages and test boards", author = "JEDEC", identifier = "JESD51 series", url = "https://www.jedec.org/" },
  { title = "MT-093 Tutorial: Thermal Design Basics", author = "Analog Devices", identifier = "MT-093", url = "https://www.analog.com/" },
]
+++

The pitfall: taking θJA (junction-to-ambient thermal resistance) from the datasheet, multiplying by dissipated power, adding room temperature, and concluding the part is fine. It usually is not, and the reason is what θJA actually measures.

θJA is measured under the JEDEC JESD51 family of test methods: the package is soldered to a standardised test board of defined size, copper area, and layer count, and placed in a defined volume of still air or a defined airflow. The number is a way of comparing packages with each other under identical conditions. It is not a property of the package alone, because most of the heat leaves through the board, and the board in the test is not your board. Your copper area is different, your via count is different, the parts next to it are heating the same copper, and the air around it is the air inside your enclosure, which is neither still-air-in-a-large-box nor at room temperature.

Datasheets often note which test board a figure refers to, and some publish two θJA values for the same package on two different boards that differ by a factor of two or more. That spread is the honest measure of how little θJA alone tells you about your design.

What to use instead:

- θJC (junction-to-case) or θJB (junction-to-board) for the part of the path that really is inside the package, then your own estimate or measurement for the path from case or board to ambient.
- ψJT (junction-to-top) together with a thermocouple or infrared reading on top of the package under worst-case load, to back-compute the junction temperature in the real enclosure. This is the measurement the vendor documents intend you to make.
- For exposed-pad packages, the rating assumes the pad is soldered to a copper area with thermal vias to other layers. An unsoldered pad, or a pad on a small isolated island, can multiply the effective resistance.

Use θJA for a first order-of-magnitude check and for choosing between packages. Do not use it as the number that says the design is safe.
