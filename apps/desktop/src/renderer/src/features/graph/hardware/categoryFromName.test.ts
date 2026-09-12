import { describe, expect, it } from 'vitest'
import { categoryFromName } from './categoryFromName'

describe('categoryFromName', () => {
  it.each([
    ['Wrist servo', 'actuators'],
    ['12V DC MOTOR', 'actuators'],
    ['pneumatic valve', 'actuators'],
    ['linear rail actuator', 'actuators'],
    ['Wrist IMU', 'sensors'],
    ['depth camera', 'sensors'],
    ['thermocouple amp', 'sensors'],
    ['wheel encoder', 'sensors'],
    ['4S LiPo pack', 'power'],
    ['5V regulator', 'power'],
    ['main controller', 'controllers'],
    ['breakout board', 'controllers'],
    ['compute module', 'controllers'],
    ['parallel gripper', 'end_effectors'],
    ['suction cup', 'end_effectors'],
    ['servo cable', 'actuators'],
    ['wiring harness', 'wiring'],
    ['2.54 mm header', 'wiring'],
    ['aluminium bracket', 'structure'],
    ['', 'structure']
  ])('guesses %j → %s', (name, category) => {
    expect(categoryFromName(name)).toEqual({ category, guessed: true })
  })

  it('matches whole words only for the short tokens', () => {
    expect(categoryFromName('pi 5').category).toBe('controllers')
    expect(categoryFromName('pipe').category).toBe('structure')
    expect(categoryFromName('escape hatch').category).toBe('structure')
  })
})
