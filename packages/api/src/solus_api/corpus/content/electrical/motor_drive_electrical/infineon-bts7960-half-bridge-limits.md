+++
title = "BTS7960 half bridge: the supply, current, PWM, and sense-ratio facts from the datasheet"
kind = "reference_value"
audience = "reference"
applicability = []
derivation = "facts_extracted"
confidence = 0.9
confidence_basis = "vendor_stated"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:electrical/motor_drive_electrical/microchip-current-sensing-high-side-vs-low-side", "corpus:electrical/motor_drive_electrical/regen-into-a-supply-that-cannot-sink"]
further_reading = []
corpus_version = "0.2.0"
revised_in = "0.2.0"

[provenance]
source_class = "datasheet"
source_title = "BTS 7960 High Current PN Half Bridge (NovalithIC) Data Sheet, Rev. 1.1"
source_publisher = "Infineon Technologies"
source_url = "https://www.infineon.com/assets/row/public/documents/10/57/infineon-bts7960-ds-en.pdf"
source_locator = "Rev. 1.1, 2004-12-07: p. 1 features, §3 Maximum Ratings (3.0.1–3.0.11), §4.1.1, §4.3.2–4.3.4, §4.4.6"
source_license = "datasheet-terms"
accessed_at = 2026-09-06
attribution = "Infineon Technologies, BTS 7960 High Current PN Half Bridge (NovalithIC) Data Sheet, Rev. 1.1, Rev. 1.1, 2004-12-07: p. 1 features, §3 Maximum Ratings (3.0.1–3.0.11), §4.1.1, §4.3.2–4.3.4, §4.4.6"
+++

The BTS7960 is the half bridge inside the ubiquitous "43 A" dual-bridge motor-driver modules,
so its datasheet limits are the module's limits. Facts extracted from Infineon's Rev. 1.1
datasheet:

What it is. One high-side and one low-side switch with driver in a P-TO-263-7 package, rated as
43 A with on-resistances of 7 mΩ (high side) plus 9 mΩ (low side), intended for protected
high-current PWM motor drives; two devices make an H-bridge.

Supply. Operating supply voltage 5.5 V to 27.5 V (§4.1.1). Absolute maximum supply −0.3 V to
45 V (3.0.1). Logic input maximum 5.3 V (3.0.2), so 3.3 V and 5 V controllers both drive it
directly.

Current. Continuous drain current is limited to ±40 A with the case below 85 °C (3.0.3), and
pulsed to ±60 A for 10 ms (3.0.4/3.0.5), with the datasheet's own footnote that the reachable
current may be smaller depending on the current-limitation level. The built-in switched-mode
current limitation acts at 43 A typical (features, §4.3.4). In practice the package and the
module's heatsinking, not the silicon, set the usable continuous current well below 40 A.

PWM. Up to 25 kHz with active freewheeling (features), and a slew-rate adjustment pin (SR) whose
allowed voltage is −0.3 V to 1.0 V (3.0.6); slower edges lower EMI at the cost of switching loss.

Protection. Overtemperature shutdown with latch behaviour, undervoltage shutdown, overvoltage
protection, and short-circuit protection (features, §4.3.2–4.3.3); junction temperature −40 °C
to 150 °C (3.0.9).

Current sense. The IS pin sources a current proportional to load current with a typical sense
ratio k_ILIS of 8,500 (§4.4.6), and the datasheet's example uses a 1 kΩ resistor from IS to
ground to make the sense voltage; fault conditions are signalled on the same pin as a distinct
fault current (§4.3). The IS pin's maximum voltage is set by that resistor and must stay within
its rating (3.0.8).

Not stated here: whether this part is current or superseded. Check Infineon's product page for
lifecycle status before a new design.
