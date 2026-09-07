// SolusTelemetry — emit Solus LB-06 telemetry as JSON lines over any Stream (MIT).
//
//   SolusTelemetry telemetry(Serial, "usb:5B42134331");
//   telemetry.begin();
//   telemetry.add("base.velocity", 0.1234f, "m/s");
//   telemetry.send();   // one line, then the channel list is empty again
//
// Line format (identical key order to the Python and MicroPython emitters):
//   {"schema_version":1,"device_id":"usb:5B42134331","ts_us":1234567,
//    "values":{"base.velocity":0.1234},"seq":0,"units":{"base.velocity":"m/s"}}
//
// ts_us is micros(): microseconds since boot in a uint32, wrapping every ~71.6 minutes. Solus
// orders samples by seq, so the wrap costs nothing; it is simply not a wall clock.
// Values print with 4 decimals. add() stores POINTERS to name and unit, not copies — pass string
// literals, or keep the strings alive until send().
#ifndef SOLUS_TELEMETRY_H
#define SOLUS_TELEMETRY_H

#include <Arduino.h>
#include <stddef.h>
#include <stdint.h>

class SolusTelemetry {
 public:
  static const uint8_t kMaxChannels = 16;

  SolusTelemetry(Stream& out, const char* deviceId);
  // Resets seq to 0 and clears any pending channels.
  void begin();
  // Queues one channel for the next send(). Returns false (and queues nothing) when the line is
  // full, the name is empty or longer than 128, the unit is empty or longer than 32, or the value
  // is not finite or |value| >= 1e9 (4 fixed decimals carry no information there in float).
  bool add(const char* name, float value, const char* unit = nullptr);
  // Prints one line for the queued channels, bumps seq and clears the queue. No channels: no line.
  void send();
  uint32_t seq() const { return seq_; }

 private:
  void printJsonString(const char* s);
  void printFixed4(float v);

  Stream& out_;
  const char* deviceId_;
  const char* names_[kMaxChannels];
  float values_[kMaxChannels];
  const char* units_[kMaxChannels];
  uint8_t count_;
  bool anyUnit_;
  uint32_t seq_;
};

#endif  // SOLUS_TELEMETRY_H
