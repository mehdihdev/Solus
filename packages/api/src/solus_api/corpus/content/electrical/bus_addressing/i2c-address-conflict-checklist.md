+++
title = "Pitfall: the I2C addresses that collide in robot sensor stacks, and how to find a hidden one"
kind = "pitfall"
audience = "reference"
applicability = [{ key = "bus", value = "i2c" }]
derivation = "solus_original"
confidence = 0.85
confidence_basis = "vendor_stated"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:electrical/bus_addressing/i2c-addresses-and-conflicts"]
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
  { title = "MPU-6050 Six-Axis MEMS MotionTracking device datasheet", author = "TDK InvenSense", identifier = "", url = "https://invensense.tdk.com/" },
  { title = "BMP280 digital pressure sensor datasheet", author = "Bosch Sensortec", identifier = "", url = "https://www.bosch-sensortec.com/" },
  { title = "ADS1115 16-bit ADC datasheet", author = "Texas Instruments", identifier = "", url = "https://www.ti.com/" },
  { title = "INA219 current/power monitor datasheet", author = "Texas Instruments", identifier = "", url = "https://www.ti.com/" },
  { title = "PCA9685 16-channel 12-bit PWM controller datasheet", author = "NXP Semiconductors", identifier = "", url = "https://www.nxp.com/" },
]
+++

Sensor breakout boards cluster on a small set of default addresses, so a robot that adds a second board of a familiar type collides more often than chance suggests. Defaults for parts common in robotics, from their datasheets (7-bit notation):

| Default | Devices |
| --- | --- |
| 0x68 / 0x69 | MPU-6050 family IMUs (AD0 low / high); many real-time clocks also use 0x68 |
| 0x76 / 0x77 | BMP280 / BME280 pressure and environmental sensors (SDO low / high) |
| 0x48 | ADS1115 ADC with ADDR to ground; TMP102 and several other temperature sensors |
| 0x40 | PCA9685 PWM/servo driver and INA219 current monitor with all address pins low; Si7021 and HTU21D humidity sensors |

Two IMUs, an IMU plus a clock module, a servo driver plus a current monitor: each of these is a collision with default straps.

How it usually goes wrong. The first board works. The second is added, the bus scan still shows the address, so it "sees" the device, but readings are mixed or one device's configuration writes land on both. Because I2C reports no error for a doubly acknowledged address, the fault is attributed to firmware.

What to check:

1. List every device on each bus with its 7-bit address as configured, including anything soldered onto a breakout you did not design: EEPROMs on camera and display modules, the on-board sensor of a development kit, and the multiplexers themselves.
2. Run an address scan with all devices attached and compare against the list. An acknowledgement at an address you did not list is a hidden device.
3. Confirm the address-select pins are actually strapped: a floating AD0 or SDO can read either way, and some breakouts default the strap high, not low.
4. Check notation. A library expecting 8-bit 0xD0 and a datasheet saying 0x68 describe the same part.
5. Where a collision cannot be strapped away, split the bus with a second controller or a switch, and record the segment assignment where the next person will find it.
