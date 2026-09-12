# Fixture: a MicroPython board printing four comma-separated values at 50 Hz.
import time

from machine import ADC, Pin

left = ADC(Pin(26))
right = ADC(Pin(27))
motor_l = 0.0
motor_r = 0.0
dist = 0.0
batt = 0.0

while True:
    motor_l = left.read_u16() / 65535
    motor_r = right.read_u16() / 65535
    dist = 35.0
    batt = 7.9
    print(motor_l, motor_r, dist, batt, sep=",")
    time.sleep_ms(20)
