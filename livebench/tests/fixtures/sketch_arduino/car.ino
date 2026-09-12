// Fixture: a representative hobby-car sketch — four values printed in a flat order at 50 Hz.
#include <Servo.h>

const int LEFT_PIN = 5;
const int RIGHT_PIN = 6;
const int TRIG_PIN = 9;
float motorL = 0;
float motorR = 0;
float dist = 0;
float batt = 0;

void setup() {
  Serial.begin(115200);
  pinMode(TRIG_PIN, OUTPUT);
}

void loop() {
  motorL = analogRead(A0) / 1023.0;
  motorR = analogRead(A1) / 1023.0;
  dist = readDistanceCm();
  batt = analogRead(A2) * 0.0098;
  Serial.print(motorL);
  Serial.print(",");
  Serial.print(motorR);
  Serial.print(",");
  Serial.print(dist);
  Serial.print(",");
  Serial.println(batt);
  delay(20);
}

float readDistanceCm() {
  return 35.0;
}
