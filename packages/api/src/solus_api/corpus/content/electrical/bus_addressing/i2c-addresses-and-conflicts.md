+++
title = "How I2C devices get their addresses, and what happens when two share one"
kind = "principle"
audience = "fundamentals"
applicability = [{ key = "bus", value = "i2c" }]
derivation = "solus_original"
confidence = 0.9
confidence_basis = "vendor_stated"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:electrical/bus_addressing/i2c-address-conflict-checklist", "corpus:electrical/signal_integrity/i2c-pullups-and-bus-capacitance"]
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
  { title = "I2C-bus specification and user manual", author = "NXP Semiconductors", identifier = "UM10204", url = "https://www.nxp.com/" },
  { title = "BMP280 digital pressure sensor datasheet", author = "Bosch Sensortec", identifier = "", url = "https://www.bosch-sensortec.com/" },
  { title = "MPU-6050 Six-Axis MEMS MotionTracking device datasheet", author = "TDK InvenSense", identifier = "", url = "https://invensense.tdk.com/" },
  { title = "TCA9548A Low-Voltage 8-Channel I2C Switch datasheet", author = "Texas Instruments", identifier = "", url = "https://www.ti.com/" },
]
+++

Every I2C transaction starts with the master sending a 7-bit address, and every device on the bus compares it with its own. The one that matches acknowledges and the conversation continues; the others stay silent. Seven bits give 128 addresses, of which the NXP specification (UM10204) reserves the two groups 0000 xxx and 1111 xxx for general call, start byte, high-speed master codes, 10-bit addressing, and device ID, leaving 112 for ordinary devices. A 10-bit extension exists but is rarely used by sensors.

Unlike SPI, where the master chooses whom to talk to with a wire, an I2C device's address is a property of the chip. The manufacturer fixes most of the bits and may expose the last one or two on pins: the BMP280 pressure sensor answers at 0x76 or 0x77 depending on its SDO pin, and the MPU-6050 inertial sensor at 0x68 or 0x69 depending on AD0. Many devices have no pin at all and exactly one address. Some are programmable through a register or a one-time write, and a few, such as multi-channel expanders, have three pins for eight choices.

A conflict is two devices with the same address on the same wires. Both acknowledge, both try to drive SDA during a read, and because the bus is open-drain the result is a bitwise AND of two data streams: values that look almost plausible, or a read that returns the wrong device's register. Writes go to both. Nothing reports an error.

Resolving a conflict, cheapest first: use the address pin if either device has one; move one device to a second I2C peripheral on the MCU; put an I2C switch or multiplexer such as the TCA9548A between the master and the duplicates, so each lives on its own downstream segment; or choose a different part.

One notational trap: some datasheets and libraries write the address as an 8-bit value with the read/write bit included, so 0x68 appears as 0xD0 and 0xD1. They describe the same device.
