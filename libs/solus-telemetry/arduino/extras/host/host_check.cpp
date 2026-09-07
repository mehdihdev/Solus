// Host golden-line check: prints exactly the line the library emits for the parity inputs shared
// with the Python and MicroPython tests (python/tests/test_telemetry_lib_parity.py), which
// compiles and runs this file when g++ is available.
//
//   g++ -std=c++11 -Wall -Wextra -Werror -I extras/host -I src extras/host/host_check.cpp
//       src/SolusTelemetry.cpp -o host_check && ./host_check
#include <stdio.h>

#include "SolusTelemetry.h"

unsigned long solus_host_micros = 1234567UL;

class StdoutStream : public Stream {
 public:
  size_t write(uint8_t c) override {
    putchar(c);
    return 1;
  }
};

int main() {
  StdoutStream out;
  SolusTelemetry telemetry(out, "usb:5B42134331");
  telemetry.begin();
  bool ok = telemetry.add("base.velocity", 0.1234f, "m/s");
  ok = telemetry.add("base.yaw_rate", -0.0125f, "rad/s") && ok;
  ok = telemetry.add("imu.accel_z", 9.8067f, "m/s^2") && ok;
  ok = telemetry.add("motor.current", 1.2345f, "A") && ok;
  ok = telemetry.add("battery.voltage", 11.9876f, "V") && ok;
  ok = telemetry.add("chassis.temperature", 27.1234f, "degC") && ok;
  if (!ok) return 2;
  // Rejections must not reach the line: full-precision garbage, empty name, oversize magnitude.
  if (telemetry.add("bad.nan", 0.0f / 0.0f) || telemetry.add("", 1.0f) ||
      telemetry.add("bad.huge", 2.0e9f)) {
    return 3;
  }
  telemetry.send();
  return telemetry.seq() == 1 ? 0 : 4;
}
