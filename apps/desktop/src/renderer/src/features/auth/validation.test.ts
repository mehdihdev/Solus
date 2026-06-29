import { describe, it, expect } from 'vitest'
import { validateEmail, validatePassword, validateSignup } from './validation'

describe('validateEmail', () => {
  it('accepts a well-formed address', () => {
    expect(validateEmail('maya@strider.dev')).toBeNull()
  })

  it('rejects empty input', () => {
    expect(validateEmail('')).toBe('Enter your email address')
  })

  it.each(['maya', 'maya@', 'maya@strider', '@strider.dev', 'a b@x.dev'])(
    'rejects malformed address %s',
    (bad) => {
      expect(validateEmail(bad)).toBe('Enter a valid email address')
    }
  )
})

describe('validatePassword', () => {
  it('accepts 8+ characters', () => {
    expect(validatePassword('hunter22')).toBeNull()
  })

  it('rejects empty input', () => {
    expect(validatePassword('')).toBe('Enter your password')
  })

  it('rejects short passwords', () => {
    expect(validatePassword('short')).toBe('At least 8 characters')
  })
})

describe('validateSignup', () => {
  it('returns no errors for valid input', () => {
    expect(validateSignup('maya@strider.dev', 'hunter22')).toEqual({})
  })

  it('collects both field errors', () => {
    const errors = validateSignup('nope', 'x')
    expect(errors.email).toBeDefined()
    expect(errors.password).toBeDefined()
  })
})
