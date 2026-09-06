+++
title = "Allocating CAN identifiers by priority, and giving every SPI device its own chip-select"
kind = "rule_of_thumb"
audience = "reference"
applicability = []
derivation = "solus_original"
confidence = 0.9
confidence_basis = "standard_derived"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:electrical/signal_integrity/differential-pairs-and-termination"]
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
  { title = "ISO 11898-1 Road vehicles — Controller area network (CAN) — Data link layer and physical signalling", author = "ISO", identifier = "ISO 11898-1", url = "https://www.iso.org/" },
  { title = "Introduction to the Controller Area Network (CAN)", author = "Texas Instruments", identifier = "SLOA101", url = "https://www.ti.com/" },
  { title = "MCP2515 stand-alone CAN controller with SPI interface datasheet", author = "Microchip Technology", identifier = "", url = "https://www.microchip.com/" },
]
+++

CAN identifiers. A CAN frame carries an 11-bit identifier (2048 values) or, in the extended format, a 29-bit one. The identifier is not a node address: it names the message, and any node may listen for it. When two nodes start transmitting at once, the bus arbitrates bit by bit and the frame with the numerically lower identifier wins without either being corrupted, so a lower number is a higher priority. Rules that follow:

- Assign the lowest identifiers to the messages that must never wait: emergency stop, fault broadcasts, motor command frames. Telemetry and logging go at the top of the range.
- No two nodes may transmit the same identifier. Arbitration cannot separate identical identifiers, and if their data differ the result is an error frame storm that can take the bus down. If several identical devices (say, motor controllers) share a bus, give each a base identifier offset by its node number, set by a switch, jumper, or configuration.
- Keep a written identifier map in the repository, with the payload layout and rate for each message. Higher-layer protocols such as CANopen and DroneCAN define allocation schemes; adopting one is easier than inventing one.
- Bus load is the sum of frame rates; a bus above roughly half its capacity starts delaying low-priority frames noticeably.

SPI chip-select. SPI peripherals share clock, MOSI, and MISO, and the master selects one by pulling its chip-select (almost always active-low) down. Each device needs its own chip-select line from the master; a shared select means every device answers at once and MISO is fought over. Only one select may be low at a time. The peripheral must release MISO (drive it high-impedance) when deselected; some low-cost displays and memory cards do not, and then need a buffer or their own bus. Chip-select also frames the transaction for many devices, so glitches on it during a transfer reset the peripheral's state machine. Some parts support daisy-chaining as an alternative to one select per device; the datasheet says so explicitly if they do.
