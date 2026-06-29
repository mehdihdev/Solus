// Login screen, ported from LoginPage in TestDesign/app/auth.jsx.
// Adds a magic-link option (ADR-009). Routes to the root on success, which
// decides between onboarding and the workspace home.
import { useState } from 'react'
import { useNavigate, type NavigateFunction } from 'react-router-dom'
import { Button } from '../../components/ui/Button'
import { Field } from '../../components/ui/Field'
import { Icons } from '../../components/ui/icons.constants'
import { AuthCard, AuthFooterLink, BusySubmit, InlineSuccess, OrDivider } from './AuthLayout'
import { GithubButton } from './GithubButton'
import { validateEmail, validatePassword } from './validation'
import { useAuthStore } from '../../store/authStore'

function useLoginForm(navigate: NavigateFunction): {
  email: string
  setEmail: (value: string) => void
  password: string
  setPassword: (value: string) => void
  error: string | null
  busy: boolean
  magicSent: boolean
  submit: () => Promise<void>
  magicLink: () => Promise<void>
  authorizeGitHub: () => Promise<{ error?: string }>
} {
  const signIn = useAuthStore((s) => s.signInWithPassword)
  const signInWithGitHub = useAuthStore((s) => s.signInWithGitHub)
  const sendMagicLink = useAuthStore((s) => s.sendMagicLink)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [magicSent, setMagicSent] = useState(false)

  const submit = async (): Promise<void> => {
    const emailError = validateEmail(email)
    const passwordError = validatePassword(password)
    if (emailError || passwordError) {
      setError(emailError ?? passwordError)
      return
    }
    setError(null)
    setBusy(true)
    const result = await signIn(email, password)
    setBusy(false)
    if (result.error) {
      setError(result.error)
      return
    }
    navigate('/')
  }

  const magicLink = async (): Promise<void> => {
    const emailError = validateEmail(email)
    if (emailError) {
      setError(emailError)
      return
    }
    setError(null)
    const result = await sendMagicLink(email)
    if (result.error) {
      setError(result.error)
      return
    }
    setMagicSent(true)
  }

  const authorizeGitHub = async (): Promise<{ error?: string }> => {
    const result = await signInWithGitHub()
    if (!result.error) navigate('/')
    return result
  }

  return {
    email,
    setEmail,
    password,
    setPassword,
    error,
    busy,
    magicSent,
    submit,
    magicLink,
    authorizeGitHub
  }
}

export function LoginPage(): React.JSX.Element {
  const navigate = useNavigate()
  const form = useLoginForm(navigate)
  return (
    <AuthCard
      title="Welcome back"
      sub="Sign in to your Solus workspace"
      onWordmarkClick={() => navigate('/')}
      footer={
        <AuthFooterLink
          prompt="New to Solus?"
          action="Create account"
          onClick={() => navigate('/signup')}
        />
      }
    >
      <GithubButton label="Sign in with GitHub" onAuthorize={form.authorizeGitHub} />
      <OrDivider />
      <Field
        label="EMAIL"
        type="email"
        value={form.email}
        onChange={form.setEmail}
        placeholder="you@team.dev"
        autoComplete="email"
      />
      <Field
        label="PASSWORD"
        type="password"
        value={form.password}
        onChange={form.setPassword}
        placeholder="••••••••"
        autoComplete="current-password"
        error={form.error ?? undefined}
        onSubmit={form.submit}
      />
      <BusySubmit
        busy={form.busy}
        label="Sign in"
        busyLabel="Signing in…"
        onClick={form.submit}
        style={{ marginTop: 6 }}
      />
      {form.magicSent ? (
        <InlineSuccess>Magic link sent — check your email.</InlineSuccess>
      ) : (
        <Button
          kind="bare"
          onClick={form.magicLink}
          style={{ width: '100%', marginTop: 10, fontSize: 12 }}
        >
          <Icons.mail size={14} /> Email me a magic link instead
        </Button>
      )}
    </AuthCard>
  )
}
