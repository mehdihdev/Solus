"""USB VID:PID → board table (data only).

Curated, not exhaustive — anything absent reports unknown, which is the honest answer. Grows
as boards are met in the field. A USB-serial BRIDGE identifies only the bridge chip; the MCU
behind it is unknown and never guessed (`recognition/passive.py` applies that rule).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Final


class BoardClass(enum.StrEnum):
    MCU_BOARD = "mcu_board"  # the USB identity IS the board (native-USB MCU boards)
    USB_BRIDGE = "usb_bridge"  # a serial front-end; says nothing about what's behind it


@dataclass(frozen=True)
class Board:
    name: str
    kind: BoardClass


BOARD_TABLE: Final[dict[tuple[int, int], Board]] = {
    # MCU boards with native USB identity
    (0x16C0, 0x0483): Board("Teensy (PJRC) 3.x/4.x USB serial", BoardClass.MCU_BOARD),
    (0x2341, 0x0043): Board("Arduino Uno R3", BoardClass.MCU_BOARD),
    (0x2341, 0x8036): Board("Arduino Leonardo", BoardClass.MCU_BOARD),
    (0x2341, 0x0042): Board("Arduino Mega 2560", BoardClass.MCU_BOARD),
    (0x303A, 0x1001): Board("Espressif ESP32-S3 native USB", BoardClass.MCU_BOARD),
    (0x239A, 0x80F4): Board("Adafruit Feather RP2040", BoardClass.MCU_BOARD),
    (0x2E8A, 0x0005): Board("Raspberry Pi Pico (RP2040, MicroPython)", BoardClass.MCU_BOARD),
    # USB-UART bridges — the chip is known; the MCU behind it is NOT
    (0x1A86, 0x55D3): Board("WCH CH343/CH9102 USB-serial bridge", BoardClass.USB_BRIDGE),
    (0x1A86, 0x7523): Board("WCH CH340 USB-serial bridge", BoardClass.USB_BRIDGE),
    (0x10C4, 0xEA60): Board("Silicon Labs CP210x USB-serial bridge", BoardClass.USB_BRIDGE),
    (0x0403, 0x6001): Board("FTDI FT232R USB-serial bridge", BoardClass.USB_BRIDGE),
    (0x0403, 0x6014): Board("FTDI FT232H USB-serial bridge", BoardClass.USB_BRIDGE),
    (0x067B, 0x2303): Board("Prolific PL2303 USB-serial bridge", BoardClass.USB_BRIDGE),
}
