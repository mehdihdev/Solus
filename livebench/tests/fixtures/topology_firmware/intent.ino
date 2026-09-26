#include <Wire.h>
#include <Servo.h>
Servo elbow;
void setup() {
  Wire.begin();
  elbow.attach(ELBOW_PIN);
  analogRead(A0);
  analogRead(2);
  // Wire.begin(); analogRead(A9);
  const char* ignored = "analogRead(A8)";
}
