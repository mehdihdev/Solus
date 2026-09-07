+++
title = "Feetech STS3215 (7.4 V edition): the specification-sheet numbers behind the SO-101 arm"
kind = "reference_value"
audience = "reference"
applicability = [{ key = "bus", value = "uart" }]
derivation = "facts_extracted"
confidence = 0.85
confidence_basis = "vendor_stated"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:robotics/actuator_selection/stall-torque-is-not-a-rating", "corpus:robotics/actuator_selection/size-from-the-load-not-the-catalogue"]
further_reading = []
corpus_version = "0.2.0"
revised_in = "0.2.0"

[provenance]
source_class = "datasheet"
source_title = "STS3215 Product Specification, edition A/0 (7.4 V 19 kg·cm plastic-case metal-gear magnetic-encoder dual-shaft TTL serial servo)"
source_publisher = "Shenzhen Feetech RC Model Co., Ltd."
source_url = "https://www.feetechrc.com/Data/feetechrc/upload/file/20200611/6372749961523760249976542.pdf"
source_locator = "edition A/0, 2020-04-10, §1, §5 Electrical Specification (5-1 to 5-11), §6 Mechanical Specification, §7-1 Control Specification"
source_license = "datasheet-terms"
accessed_at = 2026-09-06
attribution = "Shenzhen Feetech RC Model Co., Ltd., STS3215 Product Specification, edition A/0 (7.4 V 19 kg·cm plastic-case metal-gear magnetic-encoder dual-shaft TTL serial servo), edition A/0, 2020-04-10, §1, §5 Electrical Specification (5-1 to 5-11), §6 Mechanical Specification, §7-1 Control Specification"
+++

The STS3215 is the actuator in the SO-101 leader and follower arms. Facts extracted from
Feetech's own product specification for the 7.4 V edition (A/0, 2020-04-10); the 12 V
variant sold under the same name has different numbers and its own sheet.

Electrical (§5), given at 6 V and at 7.4 V respectively:

- No-load speed: 0.238 s/60° (42 rpm) and 0.192 s/60° (52 rpm).
- No-load running current: 130 mA and 150 mA; idle current 6 mA.
- Stall torque: 16.5 kg·cm and 19.5 kg·cm (about 1.6 and 1.9 N·m); stall current 2 A and 2.5 A.
- Rated torque: 4 kg·cm and 5 kg·cm at 500 mA and 650 mA rated current. The rated figure, not
  the stall figure, is what the servo can hold continuously.
- Input voltage range 4 V to 7.4 V; motor terminal resistance 2.5 Ω; torque constant 8 kg·cm/A.

Mechanical (§6): 45.2 × 24.7 × 35 mm, 55 ± 1 g; no mechanical angle limit; PA+GF case, copper
gears, ball bearings; gear ratio 1/345; backlash ≤ 0.5°; 25-tooth 5.9 mm output horn with an
M3×6 horn screw; 12-bit magnetic angle sensor over 360° with unlimited life; connector 5264-3P
with a 15 cm cable, pins 1 GND, 2 Vcc, 3 Signal/TTL.

Control (§7-1): half-duplex asynchronous serial, 8 data bits, 1 stop, no parity; baud 38,400 to
1 Mbps, factory default 1 Mbps; IDs 0–253; PID control with editable gains; neutral 180° at
count 2048; 360° over counts 0–4096 at 0.088°/count; clockwise increasing by default; feedback of
load, position, speed, input voltage, current, and temperature.

Environment (§1): storage −30 °C to 80 °C, operating −20 °C to 60 °C.

What to do with these numbers: the SO-101 follower runs six of these at 1/345 through the
bus; six stalled servos at 7.4 V draw 15 A, which is the power-budget figure, while six holding a
rated load draw about 4 A. The 1/345 ratio and the 4096-count encoder give 0.088° at the output;
the leader arm's other ratios (1/147 and 1/191) are different builds of the same servo family.
