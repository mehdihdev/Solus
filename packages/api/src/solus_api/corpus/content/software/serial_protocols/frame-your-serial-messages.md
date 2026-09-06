+++
title = "Serial is a byte stream, not a message stream: frame, check, version, and time out"
kind = "principle"
audience = "fundamentals"
applicability = [{ key = "bus", value = "uart" }]
derivation = "solus_original"
confidence = 0.85
confidence_basis = "consensus"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:software/embedded_patterns/isr-discipline", "corpus:software/real_time_constraints/delay-in-a-control-loop"]
corpus_version = "0.1.0"
revised_in = "0.1.0"

[provenance]
source_class = "solus_authored"
source_title = "Solus engineering corpus"
source_publisher = "Solus"
source_license = "solus-proprietary"
accessed_at = 2026-09-06
checked_against = [
  { title = "Arduino Language Reference: Serial (buffer behaviour, available(), readBytes(), setTimeout())", author = "Arduino", identifier = "Arduino language reference, Serial", url = "https://www.arduino.cc/" },
  { title = "Zephyr Project documentation: UART driver API (polling, interrupt-driven, and asynchronous modes)", author = "Zephyr Project", identifier = "Zephyr docs, UART", url = "https://docs.zephyrproject.org/" },
  { title = "micro-ROS documentation: serial transport and client-agent framing", author = "micro-ROS project (eProsima and partners)", identifier = "micro-ROS docs", url = "https://micro.ros.org/" },
]
+++

A UART, a USB CDC port, or an RS-485 link delivers bytes in order, with no notion of where one message ends and the next begins, and with no guarantee that every byte arrives. Everything that makes it usable for a robot is layered on by you.

Why unframed ASCII breaks at speed. `Serial.println("123,456")` looks like a message, but the receiver sees a fragment when a read lands mid-line, `12456` when a byte is lost, and a truncated line whenever its input buffer (64 bytes on the classic ATmega328P Arduino boards) overflows because the main loop was busy. It survives at 9600 baud with one sensor; at 115200 baud with a 500 Hz stream it does not, and the bugs look like sensor noise.

The four parts of a robust framing layer:

1. Framing: a way to find message boundaries after losing sync. Either a start byte plus a length field, or a delimiter byte that never appears inside the payload. Delimiter schemes need escaping (COBS or SLIP-style byte stuffing) so a payload byte equal to the delimiter does not end the frame early. Length-prefixed schemes need a sync byte and a sanity bound on the length, so a corrupted length cannot stall the parser.
2. Integrity check: a CRC over the payload (CRC-16 or CRC-32; CRC-8 for very short frames). A plain additive checksum misses swapped bytes and many multi-bit errors, and XOR misses more. On a failed check, drop the frame and resynchronise; never "repair" it.
3. Versioning: a message type or schema id in the header, and a protocol version exchanged at connect, so a firmware and host that disagree fail loudly instead of decoding fields as the wrong type. Never change the meaning of an existing field id; add a new one.
4. Timeouts: a per-frame receive timeout (if a frame does not complete within a few frame-times, discard the partial one and resync) and a link-level heartbeat so each side knows the other is alive. A motor controller that keeps applying the last command after the host has crashed is a safety failure.

Prefer binary over ASCII once you have framing: fixed-width fields are smaller, parse in constant time, and avoid float formatting on the MCU. micro-ROS's serial transport and most flight-controller protocols have this shape (sync, length, id, payload, CRC).

Implement the receiver as a byte-at-a-time state machine (waiting for sync, reading header, reading payload, checking CRC) fed from the UART interrupt or a ring buffer. A receiver that calls a blocking `readBytes` to wait for a whole frame stalls the rest of the loop.
