// Post-signup "check your email" screen. Supabase has sent a confirmation link;
// until the user clicks it there is no session. We quietly retry sign-in on an
// interval, so the moment they confirm in their email, the app logs in and the
// router carries them into onboarding — no manual step back in the app.
import { useEffect, useRef, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Spinner } from '../../components/ui/Spinner'
import { Icons } from '../../components/ui/icons.constants'
import { AuthCard, AuthFooterLink, BusySubmit, InlineSuccess } from './AuthLayout'
import { useAuthStore } from '../../store/authStore'

const POLL_MS = 4000

interface ConfirmEmailNoticeProps {
  email: string
  password: string
  onUseDifferentEmail: () => void
}

/** Retry sign-in on an interval until the user confirms their email elsewhere. */
function usePollForConfirmation(email: string, password: string): void {
  const signIn = useAuthStore((s) => s.signInWithPassword)
  const inFlight = useRef(false)
  useEffect(() => {
    const attempt = async (): Promise<void> => {
      if (inFlight.current) return
      inFlight.current = true
      try {
        await signIn(email, password)
      } finally {
        inFlight.current = false
      }
    }
    const id = setInterval(attempt, POLL_MS)
    return () => clearInterval(id)
  }, [email, password, signIn])
}

export function ConfirmEmailNotice({
  email,
  password,
  onUseDifferentEmail
}: ConfirmEmailNoticeProps): React.JSX.Element {
  const signIn = useAuthStore((s) => s.signInWithPassword)
  const resend = useAuthStore((s) => s.resendConfirmation)
  const [checking, setChecking] = useState(false)
  const [resent, setResent] = useState(false)

  // Once the email is confirmed the polled sign-in succeeds, the session is set,
  // and the route guard navigates away (unmounting this screen).
  usePollForConfirmation(email, password)

  const checkNow = async (): Promise<void> => {
    setChecking(true)
    await signIn(email, password)
    setChecking(false)
  }

  const doResend = async (): Promise<void> => {
    await resend(email)
    setResent(true)
  }

  return (
    <AuthCard
      title="Confirm your email"
      sub={`We sent a confirmation link to ${email}. Click it and you'll be signed in here automatically.`}
      footer={
        <AuthFooterLink
          prompt="Wrong address?"
          action="Use a different email"
          onClick={onUseDifferentEmail}
        />
      }
    >
      <div
        style={{
          display: 'flex',
          gap: 10,
          alignItems: 'center',
          justifyContent: 'center',
          color: 'var(--mut)',
          fontSize: 12.5,
          padding: '4px 0 18px'
        }}
      >
        <Spinner /> Waiting for confirmation…
      </div>
      <BusySubmit
        busy={checking}
        label="I've confirmed — continue"
        busyLabel="Checking…"
        onClick={checkNow}
      />
      {resent ? (
        <InlineSuccess>Confirmation email re-sent.</InlineSuccess>
      ) : (
        <Button
          kind="bare"
          onClick={doResend}
          style={{ width: '100%', marginTop: 10, fontSize: 12 }}
        >
          <Icons.mail size={14} /> Resend confirmation email
        </Button>
      )}
    </AuthCard>
  )
}
