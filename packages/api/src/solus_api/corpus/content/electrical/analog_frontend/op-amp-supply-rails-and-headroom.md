+++
title = "An op amp cannot swing to its rails, and 'rail-to-rail' has fine print"
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
related = ["corpus:electrical/analog_frontend/adc-reference-resolution-and-lsb", "corpus:electrical/analog_frontend/input-bias-offset-excitation-antialias"]
further_reading = [
  { title = "The Art of Electronics", author = "Horowitz, Hill", identifier = "ISBN 978-0521809269" },
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
  { title = "MT-035 Op Amp Inputs, Outputs, Single-Supply, and Rail-to-Rail Issues", author = "Analog Devices", identifier = "MT-035", url = "https://www.analog.com/" },
  { title = "Op Amps for Everyone", author = "Texas Instruments", identifier = "SLOD006", url = "https://www.ti.com/" },
]
+++

An operational amplifier is powered from two supply pins, and nothing it does can produce a voltage outside them. That much is obvious. What surprises people coming from software or mechanical work is how far inside the rails the usable range actually stops.

Output. A classic bipolar op amp's output stage may stop 1–2 V short of each rail. On a 5 V single supply that leaves perhaps 1.5 V to 3.5 V of usable output, and a sensor signal that should read 0.2 V comes out as a flat 1.5 V. Parts sold as rail-to-rail output get within tens of millivolts of the rails, but only when lightly loaded; the datasheet gives the swing at a specified load current, and it degrades as the load increases.

Input. The input common-mode range is a separate specification. Many op amps cannot follow an input that goes all the way to one rail; a bipolar-input part on a single supply often cannot sense a signal at ground. Rail-to-rail input parts can, usually by switching between two input stages, and that crossover produces a small offset step somewhere in the range, which matters for precision work. Driving an input outside its range does not merely clip: some parts invert their output (phase reversal), which in a control loop is dangerous.

Single-supply sensing. If the sensor signal sits near 0 V and there is no negative rail, three honest options exist: choose an amplifier whose input range includes ground and whose output swings close to it (and accept it will not reach exactly 0 V); bias the signal up to mid-supply and subtract the offset in software; or provide a small negative rail with a charge-pump inverter.

Symptoms of a rail problem: a reading that flat-lines at a fixed value well above zero or below full scale; a gain stage whose output stops tracking above some input; an ADC channel that never reads below a few hundred counts. Check the amplifier's output swing and input common-mode range on the datasheet against the actual supply, not the one on the schematic symbol. Analog Devices' MT-035 covers the behaviour in detail.
