// Describe something new (SOLUSDEV-250 P3): a deterministic keyword rule over the
// name guesses the robot category. Always a guess — the UI says so and lets the
// user change it. Generic words only; no product or vendor name lives here.
import type { RobotCategory } from '../../../lib/api/hardware'

export interface CategoryGuess {
  category: RobotCategory
  guessed: true
}

// Prefix tokens match "accelerometer", "temperature"…; short tokens are whole words.
const RULES: readonly (readonly [RegExp, RobotCategory])[] = [
  [/\b(motor|servo|actuator|linear|pump|valve)|\besc\b/, 'actuators'],
  [
    /\b(gyro|accel|lidar|camera|sensor|encoder|ultrasonic|distance|thermo|temp|pressure|mag)|\b(imu|gps)\b/,
    'sensors'
  ],
  [/\b(battery|lipo|regulator|charger|power|psu)|\bbec\b/, 'power'],
  [/\b(controller|board|compute)|\b(mcu|soc|pi)\b/, 'controllers'],
  [/\b(gripper|suction|effector|tool)|\bhand\b/, 'end_effectors'],
  [/\b(cable|wire|connector|harness|header)/, 'wiring']
]

export function categoryFromName(name: string): CategoryGuess {
  const lower = name.toLowerCase()
  const hit = RULES.find(([pattern]) => pattern.test(lower))
  return { category: hit?.[1] ?? 'structure', guessed: true }
}
