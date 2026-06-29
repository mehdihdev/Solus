// Pure client-side validation for the auth doorway. Mirrors the rules in
// TestDesign/app/auth.jsx. These are UX guards only — Supabase enforces the
// real constraints server-side.

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/
const MIN_PASSWORD_LENGTH = 8

export function validateEmail(email: string): string | null {
  if (!email.trim()) return 'Enter your email address'
  if (!EMAIL_RE.test(email)) return 'Enter a valid email address'
  return null
}

export function validatePassword(password: string): string | null {
  if (!password) return 'Enter your password'
  if (password.length < MIN_PASSWORD_LENGTH) return `At least ${MIN_PASSWORD_LENGTH} characters`
  return null
}

export interface SignupErrors {
  email?: string
  password?: string
}

/** Validate the signup form; empty object means valid. */
export function validateSignup(email: string, password: string): SignupErrors {
  const errors: SignupErrors = {}
  const emailError = validateEmail(email)
  const passwordError = validatePassword(password)
  if (emailError) errors.email = emailError
  if (passwordError) errors.password = passwordError
  return errors
}
