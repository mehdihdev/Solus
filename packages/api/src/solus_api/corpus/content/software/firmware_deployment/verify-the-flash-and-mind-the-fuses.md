+++
title = "Flashing is not done until it is verified, and fuses and option bytes are one-way doors"
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
related = ["corpus:software/embedded_patterns/watchdog-fed-from-the-wrong-place"]
corpus_version = "0.1.0"
revised_in = "0.1.0"

[provenance]
source_class = "solus_authored"
source_title = "Solus engineering corpus"
source_publisher = "Solus"
source_license = "solus-proprietary"
accessed_at = 2026-09-06
checked_against = [
  { title = "Arduino CLI documentation: arduino-cli upload and the verify option", author = "Arduino", identifier = "Arduino CLI docs", url = "https://www.arduino.cc/" },
  { title = "ATmega328P datasheet: fuse bits (clock selection, RSTDISBL, SPIEN) and serial/parallel programming", author = "Microchip Technology", identifier = "ATmega328P datasheet", url = "https://www.microchip.com/" },
  { title = "STM32 microcontroller system memory boot mode (bootloader) and reference-manual option bytes / read-out protection levels", author = "STMicroelectronics", identifier = "AN2606; RM0090", url = "https://www.st.com/" },
  { title = "ESP-IDF Programming Guide: eFuse, Flash Encryption, Secure Boot, OTA partitions", author = "Espressif Systems", identifier = "ESP-IDF docs", url = "https://docs.espressif.com/" },
  { title = "Zephyr Project documentation: MCUboot image slots and swap-based upgrade", author = "Zephyr Project", identifier = "Zephyr docs, MCUboot", url = "https://docs.zephyrproject.org/" },
]
+++

Getting an image onto a microcontroller has three routes, and a robot team eventually uses all of them:

- A serial bootloader (Arduino's, the STM32 built-in system bootloader, the ESP32 ROM loader) needs only a UART or USB port, is what `arduino-cli upload` and `esptool` drive, and can be done from the robot's own host computer in the field. It requires an intact bootloader and the chip put into bootloader mode.
- A debug probe over SWD or JTAG (ST-LINK, J-Link, a Pico as a probe) works even when the bootloader is erased or the application hangs at reset, and gives you breakpoints. Leave the debug pins on a header; omitting them to save space is regretted at the first bricked unit.
- An in-application update (firmware receives a new image over its own link and a bootloader such as MCUboot swaps it in) is the only route that works once the board is inside a sealed enclosure.

Verification. A programmer that reports "done" has usually only written. Read the flash back and compare, or have the firmware compute a CRC over its image at boot and report it. The tools do this on request (`arduino-cli upload --verify`, `esptool verify_flash`, the verify option in STM32CubeProgrammer). Embed a build id or git hash in the image and print it at boot, so a mismatched board is caught on the first log line.

Rollback. A bootloader with two image slots (MCUboot swap, or the ESP-IDF OTA partition scheme) reverts to the previous image if the new one fails to mark itself good within a timeout. Without slots, keep the last known-good binary and its hash with the release.

Fuses and option bytes are the one-way doors:

- AVR fuses select the clock source and can disable the reset pin (RSTDISBL) or SPI programming (SPIEN). Select an external crystal on a board without one and the chip will neither run nor accept ISP commands until you inject a clock; disable reset and ISP is gone for good (only high-voltage programming recovers it). Write fuses from a reviewed script.
- STM32 option bytes set read-out protection. RDP level 1 is reversible with a mass erase; level 2 is designed to be permanent, disabling the debug port and the system bootloader. Confirm which level a production script sets before it touches a board you still need.
- ESP32 eFuses are one-time programmable: flash encryption and secure boot cannot be undone once burned. Test the pipeline on a sacrificial module first.

Keep the flashing procedure (tool version, command, fuse or option-byte values, verification step) in the repository and treat changes to it as code changes.
