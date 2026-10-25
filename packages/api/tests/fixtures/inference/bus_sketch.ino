// Fixture for graph/inference/firmware_edges (SOLUSDEV-320 Phase 3).
// One real bus address write, one commented decoy that must never produce an edge.
#include <Wire.h>

const int SERVO_ADDRESS = 3;

void setup() {
  Wire.begin();
  // Wire.beginTransmission(0x09);  decoy: a commented-out address is not evidence
  Wire.beginTransmission(0x03);
  Wire.write(0x01);
  Wire.endTransmission();
}

void loop() {
  int reading = analogRead(A0);
  (void)reading;
}
