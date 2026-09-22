// Password reset (SOLUSDEV-82). In-app recovery flow — no browser redirect:
// step 1 sends a recovery code to the email; step 2 verifies the code and sets
// a new password (authStore.confirmPasswordReset), then returns to sign-in.
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Field } from '../../components/ui/Field'
import { AuthCard, AuthFooterLink, BusySubmit, InlineSuccess } from './AuthLayout'
import { validateEmail, validatePassword } from './validation'
import { useAuthStore } from '../../store/authStore'

type Step = 'request' | 'confirm'

function usePasswordReset() {
  const navigate = useNavigate()
  const requestReset = useAuthStore((s) => s.requestPasswordReset)
  const confirmReset = useAuthStore((s) => s.confirmPasswordReset)

  const [step, setStep] = useState<Step>('request')
  const [email, setEmail] = useState('')
  const [code, setCode] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState(false)

  const sendCode = async (): Promise<void> => {
    const emailError = validateEmail(email)
    if (emailError) return setError(emailError)
    setError(null)
    setBusy(true)
    const result = await requestReset(email)
    setBusy(false)
    if (result.error) return setError(result.error)
    setStep('confirm')
  }

  const setNewPassword = async (): Promise<void> => {
    const passwordError = validatePassword(password)
    if (!code.trim()) return setError('Enter the code from your email.')
    if (passwordError) return setError(passwordError)
    setError(null)
    setBusy(true)
    const result = await confirmReset(email, code.trim(), password)
    setBusy(false)
    if (result.error) return setError(result.error)
    setDone(true)
  }

  return {
    navigate,
    step,
    email,
    setEmail,
    code,
    setCode,
    password,
    setPassword,
    error,
    busy,
    done,
    sendCode,
    setNewPassword
  }
}

export function ResetPasswordPage(): React.JSX.Element {
  const {
    navigate,
    step,
    email,
    setEmail,
    code,
    setCode,
    password,
    setPassword,
    error,
    busy,
    done,
    sendCode,
    setNewPassword
  } = usePasswordReset()
  return (
    <AuthCard
      title="Reset your password"
      sub={
        step === 'request'
          ? 'We’ll email you a recovery code'
          : 'Enter the code we emailed and choose a new password'
      }
      onWordmarkClick={() => navigate('/')}
      footer={
        <AuthFooterLink
          prompt="Remembered it?"
          action="Back to sign in"
          onClick={() => navigate('/login')}
        />
      }
    >
      {done ? (
        <InlineSuccess>Password updated — sign in with your new password.</InlineSuccess>
      ) : step === 'request' ? (
        <RecoveryEmailForm
          email={email}
          setEmail={setEmail}
          error={error}
          sendCode={sendCode}
          busy={busy}
        />
      ) : (
        <>
          <Field
            label="RECOVERY CODE"
            type="text"
            value={code}
            onChange={setCode}
            placeholder="123456"
            autoComplete="one-time-code"
          />
          <Field
            label="NEW PASSWORD"
            type="password"
            value={password}
            onChange={setPassword}
            placeholder="••••••••"
            autoComplete="new-password"
            error={error ?? undefined}
            onSubmit={setNewPassword}
          />
          <BusySubmit
            busy={busy}
            label="Set new password"
            busyLabel="Saving…"
            onClick={setNewPassword}
            style={{ marginTop: 6 }}
          />
        </>
      )}
    </AuthCard>
  )
}

function RecoveryEmailForm({
  email,
  setEmail,
  error,
  sendCode,
  busy
}: Pick<
  ReturnType<typeof usePasswordReset>,
  'email' | 'setEmail' | 'error' | 'sendCode' | 'busy'
>): React.JSX.Element {
  return (
    <>
      <Field
        label="EMAIL"
        type="email"
        value={email}
        onChange={setEmail}
        placeholder="you@team.dev"
        autoComplete="email"
        error={error ?? undefined}
        onSubmit={sendCode}
      />
      <BusySubmit
        busy={busy}
        label="Send recovery code"
        busyLabel="Sending…"
        onClick={sendCode}
        style={{ marginTop: 6 }}
      />
    </>
  )
}
