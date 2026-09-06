+++
title = "LDO, buck, or boost: what each regulator costs you in heat, noise, and headroom"
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
related = ["corpus:electrical/power_design/battery-chemistry-c-rating-cutoff", "corpus:electrical/power_design/inrush-brownout-reverse-polarity-hotplug"]
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
  { title = "Understanding the Terms and Definitions of LDO Voltage Regulators", author = "Texas Instruments", identifier = "SLVA079", url = "https://www.ti.com/" },
  { title = "Basic Calculation of a Buck Converter's Power Stage", author = "Texas Instruments", identifier = "SLVA477", url = "https://www.ti.com/" },
  { title = "Basic Calculation of a Boost Converter's Power Stage", author = "Texas Instruments", identifier = "SLVA372", url = "https://www.ti.com/" },
]
+++

A low-dropout linear regulator (LDO) is a controlled resistor. It passes the load current straight through and burns the difference between input and output as heat:

```
P_loss ≈ (V_in − V_out) · I_out
```

Dropping 12 V to 5 V at 1 A dissipates 7 W in a part that may be rated for 1 or 2 W without a heatsink. What you get in exchange is simplicity, no switching noise, fast response, and low cost. It needs a minimum headroom, the dropout voltage, below which regulation is lost; a 3.3 V LDO with 300 mV dropout stops regulating when its input falls below about 3.6 V, which matters on a battery that sags. Use an LDO when the voltage step is small, the current is low, or the load is noise-sensitive (ADC references, RF, sensors).

A buck converter steps down by switching an inductor at tens of kilohertz to megahertz, so it moves energy rather than dissipating it. Efficiency of 80–95 % is typical depending on load and design, which is why bucks handle the big steps: battery to 5 V logic, 24 V to motor-controller logic. The price is output ripple and switching noise, layout sensitivity, more parts, and a minimum load or light-load mode behaviour to read about in the datasheet. Texas Instruments' SLVA477 walks through the inductor, capacitor, and ripple calculations.

A boost converter steps up. Input current is higher than output current by roughly the voltage ratio divided by efficiency, so a 3.7 V cell boosting to 12 V at 1 A draws over 3 A from the cell. A simple boost cannot limit its output on a short circuit, because the input feeds the output through the inductor and diode even with the switch off; check for a part with a disconnect feature if that matters. SLVA372 covers the design arithmetic.

The common robot topology is a buck from the battery to a 5 V or 3.3 V intermediate rail, then LDOs for the quiet loads. The two checks that catch most mistakes: dissipation of every LDO at maximum input voltage and current, and dropout margin at the battery's low-voltage cutoff.
