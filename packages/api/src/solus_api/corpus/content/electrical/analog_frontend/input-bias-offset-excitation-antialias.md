+++
title = "Pitfalls at the analog input: bias current into high impedance, offset times gain, and no anti-alias filter"
kind = "pitfall"
audience = "reference"
applicability = []
derivation = "solus_original"
confidence = 0.85
confidence_basis = "vendor_stated"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:electrical/analog_frontend/op-amp-supply-rails-and-headroom", "corpus:electrical/analog_frontend/adc-reference-resolution-and-lsb"]
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
  { title = "MT-038 Op Amp Input Bias Current", author = "Analog Devices", identifier = "MT-038", url = "https://www.analog.com/" },
  { title = "MT-037 Op Amp Input Offset Voltage", author = "Analog Devices", identifier = "MT-037", url = "https://www.analog.com/" },
  { title = "MT-002 What the Nyquist Criterion Means to Your Sampled Data System Design", author = "Analog Devices", identifier = "MT-002", url = "https://www.analog.com/" },
  { title = "Signal conditioning Wheatstone resistive bridge sensors", author = "Texas Instruments", identifier = "", url = "https://www.ti.com/" },
]
+++

Bias current into a high-impedance source. Every op amp input draws a small current. Multiply it by the source resistance and you get an error voltage at the input: 100 nA of bias into a 1 MΩ sensor is 100 mV, before any gain. Bipolar-input amplifiers draw nanoamps to microamps; CMOS and JFET inputs draw picoamps. For photodiodes, pH probes, high-value thermistor dividers, or any source above about 100 kΩ, choose a low-bias-current amplifier and keep the impedances seen by both inputs similar so the currents cancel. Analog Devices' MT-038 covers the mechanisms.

Offset voltage times gain. The input offset voltage is a small built-in error, tens of microvolts to several millivolts depending on the part, and it is multiplied by the closed-loop gain along with the signal. A 2 mV offset in a gain-of-100 strain-gauge stage is 200 mV at the ADC, and it drifts with temperature. Calibrating it out in software is fine for the static part; the drift needs a low-offset or zero-drift amplifier (MT-037).

Sensor excitation. Bridge and resistive sensors produce an output proportional to their excitation voltage. If the excitation wanders, the reading wanders identically. Either drive the sensor from the ADC's reference (ratiometric, the error cancels) or measure the excitation on another channel and divide. Long leads to a bridge add resistance in series with the excitation, which is why remote sensors use six-wire or Kelvin connections.

No anti-alias filter. An ADC sampling at f_s cannot tell a signal at f from one at f_s − f; energy above half the sample rate folds back into the band and looks like real signal. In a robot the aliasing sources are motor PWM, switching regulators, and servo pulses, all far above the loop bandwidth. Averaging in software does not help once the noise has aliased. Put an RC or active low-pass filter in front of the ADC with its corner below half the sample rate, and sample well above the highest frequency actually present, not just the one of interest (MT-002).

Floating and unused inputs. An unconnected op amp input or ADC channel picks up whatever field is nearby. Tie unused amplifier inputs to a defined voltage; ground unused ADC channels.
