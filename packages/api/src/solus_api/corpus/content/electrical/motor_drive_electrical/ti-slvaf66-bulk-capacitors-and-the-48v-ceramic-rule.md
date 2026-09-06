+++
title = "Bulk capacitance for a motor stage, and why a 48 V bus needs 100 V ceramics"
kind = "rule_of_thumb"
audience = "reference"
applicability = []
derivation = "facts_extracted"
confidence = 0.85
confidence_basis = "vendor_stated"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:electrical/decoupling/ceramic-dc-bias-derating", "corpus:electrical/power_design/battery-chemistry-c-rating-cutoff", "corpus:electrical/motor_drive_electrical/ti-slvaf66-coast-versus-brake-and-kelvin-sensing"]
further_reading = []
corpus_version = "0.2.0"
revised_in = "0.2.0"

[provenance]
source_class = "vendor_documentation"
source_title = "System Design Considerations for High-Power Motor Driver Applications (SLVAF66)"
source_publisher = "Texas Instruments"
source_url = "https://www.ti.com/cn/lit/an/slvaf66/slvaf66.pdf"
source_locator = "June 2021, §4.1 and §4.1.1, pp. 11–12"
source_license = "vendor-terms"
accessed_at = 2026-09-06
attribution = "Texas Instruments, SLVAF66, June 2021, §4.1 and §4.1.1, pp. 11–12"
+++

TI's high-power motor-driver application report gives practical, explicitly approximate advice on
the capacitors at a motor stage. Facts and rules extracted, with the note's own caveats:

What the capacitors are for. The supply is physically far from the bridge, so the path carries
inductance; bulk and decoupling capacitors supply the instantaneous charge that path cannot, and
they absorb energy when the motor acts as a generator so the high-side drain voltage does not
run away. Small capacitors respond fast but hold little; large ones hold a lot and respond
slowly. That is why datasheets pair them.

The starting values the note gives for a power stage: a few capacitors in the 100–330 µF range
in parallel with a few 1–2.2 µF ceramics, with spare footprints for later; and a common rule of
thumb of about 2 µF per watt, which the note immediately qualifies as varying significantly
between real systems. The note calls its own advice nebulous on purpose: the rigorous route is to
estimate the layout parasitics and simulate, and most teams instead start from the rule, test the
real system, and add or change capacitors until ringing and spikes are acceptable.

The rule that is not nebulous: ceramic DC-bias derating. A ceramic capacitor exposed to its
rated voltage delivers roughly half its nominal capacitance; the note's production example is a
10 µF 10 V part giving only 1–3 µF at 10 V bias. Hence the sizing rule: choose ceramic voltage
ratings at about 2× (sometimes relaxed to 1.5×) the voltage they will see. For a 48 V system
that means 100 V-rated ceramics (2 × 48 = 96 V, rounded to the industry value), and 48 V-rated
parts in the power stage are, in the note's words, not helpful. For 60 V the 1.5× rule also lands
at about 100 V. Even so, the note says to read the specific capacitor's bias curve, because the
guideline can still fail.

Applicability: any bridge on a bus above a few volts; the 100 V figure is specific to 48 V
systems. Electrolytics do not derate with bias this way but have their own ESR and lifetime
limits.
