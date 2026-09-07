// NanoSixChannels — six named, unit-tagged channels at 100 Hz over Serial at 115200 baud.
//
// Open the board in Solus Live Bench: the stream is recognised as LB-06 JSON lines and each
// channel appears as <part>.<quantity> with its unit. Replace the synthetic values with your
// sensor reads; keep the names in the <part>.<quantity> form and the unit in the third argument.
//
// Bandwidth: this line is ~330 bytes, and a UART carries baud/10 bytes per second, so 115200
// sustains ~35 such lines per second — print() blocks once the TX buffer fills and the loop
// slows to what the link can carry. Use a higher baud (500000/921600 on boards that support it)
// or fewer channels per line for a true 100 Hz.
#include <SolusTelemetry.h>

#include <math.h>

static const unsigned long BAUD = 115200;
static const unsigned long PERIOD_US = 10000;  // 100 Hz

// device_id: the device ref Solus shows for this board (Live Bench -> connections), usb:<USB serial>.
SolusTelemetry telemetry(Serial, "usb:5B42134331");
unsigned long nextUs = 0;

void setup() {
  Serial.begin(BAUD);
  telemetry.begin();
  nextUs = micros();
}

void loop() {
  if ((long)(micros() - nextUs) < 0) return;
  nextUs += PERIOD_US;
  float t = micros() / 1.0e6f;

  telemetry.add("base.velocity", 0.25f * sinf(t), "m/s");
  telemetry.add("base.yaw_rate", 0.10f * cosf(t), "rad/s");
  telemetry.add("imu.accel_z", 9.81f + 0.05f * sinf(3.0f * t), "m/s^2");
  telemetry.add("motor.current", 1.2f + 0.3f * sinf(0.5f * t), "A");
  telemetry.add("battery.voltage", 11.9f - 0.001f * t, "V");
  telemetry.add("chassis.temperature", 27.0f + 0.01f * t, "degC");
  telemetry.send();
}
