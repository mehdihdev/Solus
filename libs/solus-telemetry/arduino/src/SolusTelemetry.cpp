// SolusTelemetry — see SolusTelemetry.h (MIT).
#include "SolusTelemetry.h"

#include <math.h>
#include <stdio.h>
#include <string.h>

// Bounds mirror the Solus packet contract (docs/contracts/telemetry-packet.md §2).
static const size_t kMaxNameLen = 128;
static const size_t kMaxUnitLen = 32;
// Above this magnitude a float has no fractional resolution left, and "%lu" cannot hold it.
static const float kMaxMagnitude = 1.0e9f;

SolusTelemetry::SolusTelemetry(Stream& out, const char* deviceId)
    : out_(out), deviceId_(deviceId), count_(0), anyUnit_(false), seq_(0) {}

void SolusTelemetry::begin() {
  count_ = 0;
  anyUnit_ = false;
  seq_ = 0;
}

bool SolusTelemetry::add(const char* name, float value, const char* unit) {
  if (count_ >= kMaxChannels || name == nullptr || name[0] == '\0') return false;
  if (strlen(name) > kMaxNameLen || isnan(value) || isinf(value)) return false;
  if (fabsf(value) >= kMaxMagnitude) return false;
  if (unit != nullptr && (unit[0] == '\0' || strlen(unit) > kMaxUnitLen)) return false;
  names_[count_] = name;
  values_[count_] = value;
  units_[count_] = unit;
  if (unit != nullptr) anyUnit_ = true;
  count_++;
  return true;
}

void SolusTelemetry::send() {
  if (count_ == 0) return;  // a packet must carry at least one value
  out_.print("{\"schema_version\":1,\"device_id\":");
  printJsonString(deviceId_);
  out_.print(",\"ts_us\":");
  out_.print((unsigned long)micros());
  out_.print(",\"values\":{");
  for (uint8_t i = 0; i < count_; i++) {
    if (i) out_.print(',');
    printJsonString(names_[i]);
    out_.print(':');
    printFixed4(values_[i]);
  }
  out_.print("},\"seq\":");
  out_.print((unsigned long)seq_);
  if (anyUnit_) {
    out_.print(",\"units\":{");
    bool first = true;
    for (uint8_t i = 0; i < count_; i++) {
      if (units_[i] == nullptr) continue;
      if (!first) out_.print(',');
      first = false;
      printJsonString(names_[i]);
      out_.print(':');
      printJsonString(units_[i]);
    }
    out_.print('}');
  }
  out_.print("}\n");
  seq_++;
  count_ = 0;
  anyUnit_ = false;
}

// JSON string literal: escapes quote and backslash, drops control characters (a signal name
// or device id never legitimately contains one). Non-ASCII bytes pass through as UTF-8.
void SolusTelemetry::printJsonString(const char* s) {
  out_.print('"');
  for (; *s; s++) {
    unsigned char c = (unsigned char)*s;
    if (c == '"' || c == '\\') {
      out_.print('\\');
      out_.print((char)c);
    } else if (c >= 0x20) {
      out_.print((char)c);
    }
  }
  out_.print('"');
}

// Fixed 4 decimals in float arithmetic, so an AVR (float == double) and a host print the same
// bytes: -0.0125 -> "-0.0125", 9.8067 -> "9.8067", 1 -> "1.0000".
void SolusTelemetry::printFixed4(float v) {
  bool neg = v < 0.0f;
  float a = neg ? -v : v;
  unsigned long ip = (unsigned long)a;
  unsigned long fp = (unsigned long)((a - (float)ip) * 10000.0f + 0.5f);
  if (fp >= 10000UL) {
    fp -= 10000UL;
    ip += 1;
  }
  if (neg && ip == 0 && fp == 0) neg = false;  // never "-0.0000"
  char buf[24];
  snprintf(buf, sizeof buf, "%s%lu.%04lu", neg ? "-" : "", ip, fp);
  out_.print(buf);
}
