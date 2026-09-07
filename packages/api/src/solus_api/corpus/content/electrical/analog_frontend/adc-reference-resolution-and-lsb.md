+++
title = "ADC resolution: LSB size, why the reference sets accuracy, and what the bit count does not promise"
kind = "reference_value"
audience = "reference"
applicability = []
derivation = "solus_original"
confidence = 0.9
confidence_basis = "vendor_stated"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:electrical/analog_frontend/op-amp-supply-rails-and-headroom", "corpus:electrical/analog_frontend/input-bias-offset-excitation-antialias"]
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
  { title = "MT-001 Taking the Mystery out of the Infamous Formula, SNR = 6.02N + 1.76dB, and Why You Should Care", author = "Analog Devices", identifier = "MT-001", url = "https://www.analog.com/" },
  { title = "Analog Engineer's Pocket Reference", author = "Texas Instruments", identifier = "SLYW038", url = "https://www.ti.com/" },
]
+++

One least-significant bit is the reference voltage divided by the number of codes:

```
LSB = V_ref / 2^N
```

| Bits | V_ref = 3.3 V | V_ref = 5.0 V |
| --- | --- | --- |
| 10 | 3.22 mV | 4.88 mV |
| 12 | 0.81 mV | 1.22 mV |
| 16 | 50 µV | 76 µV |

That is resolution, not accuracy. Three things the bit count does not promise:

The reference. Every conversion is a ratio of input to reference, so a reference that is 1 % high makes every reading 1 % low, and reference noise appears directly in the result. A 16-bit converter behind a 1 % reference has 16 bits of resolution and roughly 7 bits of absolute accuracy. Using the MCU's VDD as the reference imports the regulator's tolerance, load-dependent droop, and switching ripple. For anything that must be absolute, use a dedicated reference IC and decouple it as its datasheet asks.

Noise. An ideal N-bit converter's quantisation noise alone limits the signal-to-noise ratio to 6.02·N + 1.76 dB (Analog Devices' MT-001 explains where the formula comes from). Real converters, amplifiers, and boards add noise, and the effective number of bits is what is left. A 16-bit ADC on a noisy board with a poor ground routinely delivers 11 or 12 usable bits; averaging recovers some of it at the cost of bandwidth.

Ratiometric measurement. When a sensor is excited from the same voltage the ADC uses as its reference (a potentiometer, a resistive bridge, a thermistor divider), reference error cancels in the ratio. This is the cheapest accuracy improvement available and it is why "just use VDD" is fine for a pot and wrong for a thermocouple amplifier.

Check: reference tolerance and temperature drift against the accuracy you need; what the reference pin is actually connected to on the board; and the ENOB figure in the ADC datasheet at your sample rate, not the headline bit count.
