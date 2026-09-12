// Fixture: a sketch whose print order depends on a branch — the parser must REFUSE to name channels.
float a = 0, b = 0, c = 0;
void setup() { Serial.begin(9600); }
void loop() {
  if (digitalRead(2)) {
    Serial.print(a); Serial.print(","); Serial.println(b);
  } else {
    Serial.print(c); Serial.print(","); Serial.println(a);
  }
  delay(100);
}
