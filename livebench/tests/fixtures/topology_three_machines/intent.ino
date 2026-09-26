// Synthetic code-intent fixture; no known attached devices.
#include <Servo.h>
#include <Wire.h>
Servo left;
void setup() {
  Wire.begin();
  left.attach(LEFT_PIN);
  analogRead(A0);
}
