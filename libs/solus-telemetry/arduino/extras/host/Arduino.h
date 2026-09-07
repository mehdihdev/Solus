// Minimal Arduino.h stand-in so SolusTelemetry.cpp compiles on a host for the golden-line check
// (extras/ is ignored by the Arduino build). Only what the library uses.
#ifndef SOLUS_HOST_ARDUINO_H
#define SOLUS_HOST_ARDUINO_H

#include <stdint.h>
#include <stdio.h>
#include <stddef.h>

class Stream {
 public:
  virtual ~Stream() {}
  virtual size_t write(uint8_t c) = 0;
  size_t print(const char* s) {
    size_t n = 0;
    for (; *s; s++) n += write((uint8_t)*s);
    return n;
  }
  size_t print(char c) { return write((uint8_t)c); }
  size_t print(unsigned long v) {
    char buf[24];
    snprintf(buf, sizeof buf, "%lu", v);
    return print(buf);
  }
};

extern unsigned long solus_host_micros;  // what micros() reports; the check pins it
inline unsigned long micros() { return solus_host_micros; }

#endif  // SOLUS_HOST_ARDUINO_H
