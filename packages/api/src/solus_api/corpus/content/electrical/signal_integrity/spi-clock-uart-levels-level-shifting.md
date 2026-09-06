+++
title = "Pitfalls: SPI over cables, UART voltage levels, and level shifters that do not shift"
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
related = ["corpus:electrical/signal_integrity/differential-pairs-and-termination", "corpus:electrical/signal_integrity/i2c-pullups-and-bus-capacitance"]
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
  { title = "Level shifting techniques in I2C-bus design", author = "NXP Semiconductors", identifier = "AN10441", url = "https://www.nxp.com/" },
  { title = "Selecting the Right Level-Translation Solution", author = "Texas Instruments", identifier = "", url = "https://www.ti.com/" },
]
+++

SPI on a cable. SPI has no termination, no error detection, and single-ended push-pull signals designed for a few centimetres of board. Over jumper wires or a ribbon cable the clock edge reflects, MISO's return trip adds to the round-trip delay, and above a few megahertz the master samples MISO before the peripheral has driven it. The failure is silent data corruption, not an error flag. Fixes in order: slow the clock, shorten the cable, add a small series resistor at the driver to damp the edge, or move the link to a bus designed for cable. Also confirm the clock polarity and phase mode (CPOL/CPHA) match the peripheral; a mismatch reads every byte shifted by one bit.

UART levels. "Serial" covers three incompatible electrical standards: 3.3 V logic-level, 5 V logic-level, and RS-232, which swings to plus and minus several volts. Connecting an RS-232 port to an MCU pin destroys the pin. A 5 V transmitter into a 3.3 V receiver is safe only if that pin is documented as 5 V tolerant; many are not. Check both ends before wiring, cross TX to RX, tie the grounds, and remember that a baud rate derived from an inaccurate internal RC oscillator drifts enough to corrupt long frames at high rates.

Level shifting. For open-drain buses such as I2C, one N-channel MOSFET per line with its gate at the lower supply passes both directions, as described in NXP's AN10441, and is the cheapest reliable translator. For push-pull unidirectional signals, a resistor divider works only for slow signals, because the divider and the receiver's input capacitance form a low-pass filter; a dedicated level-translator IC is right for SPI clocks and fast UARTs. Auto-direction-sensing translators, common on breakout boards, rely on weak internal pull-ups and fail when the bus has strong external pull-ups or long wiring; if a translator "works one way", this is usually why. TI's level-translation selection guide compares the options.

Check when a link fails intermittently: scope the clock at the receiver, not the driver; read the input voltage thresholds on both datasheets; and verify that every device on the bus shares a ground.
