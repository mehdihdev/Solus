// Signup screen, ported from SignupPage in TestDesign/app/auth.jsx.
// Wired to Supabase (or dev bypass) via authStore; routes to onboarding on success.
import { useState } from 'react'
import { useNavigate, type NavigateFunction } from 'react-router-dom'
import { Field } from '../../components/ui/Field'
import { AuthCard, AuthFooterLink, BusySubmit, OrDivider } from './AuthLayout'
import { GithubButton } from './GithubButton'
import { validateSignup, type SignupErrors } from './validation'
import { ConfirmEmailNotice } from './ConfirmEmailNotice'
import { useAuthStore } from '../../store/authStore'

interface SignupForm {
  email: string
  setEmail: (value: string) => void
  password: string
  setPassword: (value: string) => void
  errors: SignupErrors
  busy: boolean
  awaitingConfirmation: boolean
  cancelConfirmation: () => void
  submit: () => Promise<void>
  authorizeGitHub: () => Promise<{ error?: string }>
}

function useSignupForm(navigate: NavigateFunction): SignupForm {
  const signUp = useAuthStore((s) => s.signUpWithPassword)
  const signInWithGitHub = useAuthStore((s) => s.signInWithGitHub)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [errors, setErrors] = useState<SignupErrors>({})
  const [busy, setBusy] = useState(false)
  const [awaitingConfirmation, setAwaitingConfirmation] = useState(false)

  const submit = async (): Promise<void> => {
    const found = validateSignup(email, password)
    setErrors(found)
    if (Object.keys(found).length > 0) return
    setBusy(true)
    const result = await signUp(email, password)
    setBusy(false)
    if (result.error) {
      setErrors({ email: result.error })
      return
    }
    if (result.needsConfirmation) {
      // No session yet — Supabase sent a confirmation link. Hand off to the
      // confirm screen, which polls until the user clicks it.
      setAwaitingConfirmation(true)
      return
    }
    navigate('/onboarding')
  }

  const authorizeGitHub = async (): Promise<{ error?: string }> => {
    const result = await signInWithGitHub()
    if (!result.error) navigate('/onboarding')
    return result
  }

  return {
    email,
    setEmail,
    password,
    setPassword,
    errors,
    busy,
    awaitingConfirmation,
    cancelConfirmation: () => setAwaitingConfirmation(false),
    submit,
    authorizeGitHub
  }
}

export function SignupPage(): React.JSX.Element {
  const navigate = useNavigate()
  const form = useSignupForm(navigate)

  if (form.awaitingConfirmation) {
    return (
      <ConfirmEmailNotice
        email={form.email}
        password={form.password}
        onUseDifferentEmail={form.cancelConfirmation}
      />
    )
  }

  return (
    <AuthCard
      title="Create your workspace"
      sub="Free for solo builders. No credit card."
      onWordmarkClick={() => navigate('/')}
      footer={
        <AuthFooterLink
          prompt="Already have an account?"
          action="Sign in"
          onClick={() => navigate('/login')}
        />
      }
    >
      <GithubButton label="Continue with GitHub" onAuthorize={form.authorizeGitHub} />
      <OrDivider />
      <Field
        label="WORK EMAIL"
        type="email"
        value={form.email}
        onChange={form.setEmail}
        placeholder="you@team.dev"
        autoComplete="email"
        error={form.errors.email}
      />
      <Field
        label="PASSWORD"
        type="password"
        value={form.password}
        onChange={form.setPassword}
        placeholder="8+ characters"
        autoComplete="new-password"
        error={form.errors.password}
        onSubmit={form.submit}
      />
      <BusySubmit
        busy={form.busy}
        label="Create account"
        busyLabel="Creating workspace…"
        onClick={form.submit}
        style={{ marginTop: 6 }}
      />
    </AuthCard>
  )
}
