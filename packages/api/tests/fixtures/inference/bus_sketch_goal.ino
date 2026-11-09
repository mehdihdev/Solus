// Fixture for the commanded fact (graph/inference/firmware_edges, SOLUSDEV-321 P3-T2).
// One literal goal of 200 deg to bus address 3, past the fake arm's +/-150 deg position limit;
// a goal whose value is a variable states no literal; a commented-out goal is not evidence.
#include <Wire.h>

void setGoalPositionDeg(int address, int goal);

void setup() {
  Wire.begin();
}

void loop() {
  setGoalPositionDeg(3, 200);
  // setGoalPositionDeg(3, 90);  decoy: a commented-out goal is not evidence
  int reading = analogRead(A0);
  setGoalPositionDeg(3, reading);
}
