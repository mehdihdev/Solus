+++
title = "ESP32: supply range, the 500 mA rule, and the input limits that bricks boards"
kind = "reference_value"
audience = "reference"
applicability = [{ key = "mcu_family", value = "esp32" }]
derivation = "facts_extracted"
confidence = 0.9
confidence_basis = "vendor_stated"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:electrical/power_design/ldo-vs-buck-vs-boost", "corpus:electrical/power_design/inrush-brownout-reverse-polarity-hotplug"]
further_reading = []
corpus_version = "0.2.0"
revised_in = "0.2.0"

[provenance]
source_class = "datasheet"
source_title = "ESP32 Series Datasheet, Version 5.3"
source_publisher = "Espressif Systems"
source_url = "https://documentation.espressif.com/esp32_datasheet_en.pdf"
source_locator = "v5.3, §2 Pins (pin descriptions and Notes on power supply, p. 19) and §5.1 Table 5-1 Absolute Maximum Ratings"
source_license = "datasheet-terms"
accessed_at = 2026-09-06
attribution = "Espressif Systems, ESP32 Series Datasheet, Version 5.3, v5.3, §2 Pins (pin descriptions and Notes on power supply, p. 19) and §5.1 Table 5-1 Absolute Maximum Ratings"
+++

Facts extracted from Espressif's ESP32 series datasheet, each with where it lives, for the
power and interface decisions a robot board makes around this part.

Supply. The operating voltage range of the chip is 2.3 V to 3.6 V (pin descriptions for VDDA
and VDD3P3; the note on power supply, p. 19). With a single supply the datasheet recommends
3.3 V and a source able to deliver 500 mA or more: Wi-Fi transmit bursts are what set that
figure, and a regulator sized for the average current drops out during them. The CPU and
digital-I/O domain (VDD3P3_CPU) accepts 1.8 V to 3.6 V; the RTC domain and the analog domain
need 2.3 V to 3.6 V.

Absolute maximum. Table 5-1 gives the allowed input voltage on the supply domains as −0.3 V to
3.6 V. A 5 V logic line into a GPIO or a 5 V rail onto a 3.3 V module is outside the table, and
that is the most common way an ESP32 module dies in a student robot.

Brown-out and battery use. The datasheet recommends pulling CHIP_PU low when the supply is below
2.3 V and, on battery-powered designs, fitting a supply-voltage supervisor so the chip does not
attempt to boot at a voltage where the boot fails. Discharging VDD33 fully before re-applying
power ensures a proper power-on reset.

Flash and PSRAM supply. In-package flash and any external PSRAM are powered from VDD_SDIO, which
can be the internal LDO at 1.8 V or the same voltage as VDD3P3_RTC; the two memories must share a
voltage, and when 1.8 V is used a 2 kΩ resistor to ground on VDD_SDIO is specified.

Peripherals that matter for sensors and actuators: a 12-bit SAR ADC with up to 18 channels
(feature list; the ADC2 channels are shared with Wi-Fi in use), and five strapping GPIOs that
must sit at defined levels at reset (§3 Boot Configurations), so a sensor or driver that holds
one of them at the wrong level makes the board fail to boot.

Conditions: current-consumption figures in the datasheet are at 3.3 V and 25 °C ambient; check
the operating-temperature grade of the specific module. These are the datasheet's stated values
at version 5.3; the revision history shows the operating-voltage range and Table 5-1 have been
revised before, so re-read the current revision before committing a design.
