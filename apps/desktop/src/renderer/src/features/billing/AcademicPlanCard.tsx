// Academic plan card (SOLUSDEV-319, ADR-042; wireflow billing.md §Academic plan).
// One full-width card under the plan grid. The verification flow (email → code →
// done) happens inside the card. Terms and the domain hint come from the server.
import { useEffect, useRef, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Mono } from '../../components/ui/Mono'
import { Spinner } from '../../components/ui/Spinner'
import { ApiError } from '../../lib/api/envelope.types'
import type { AcademicStatus } from '../../lib/api/resources.academic'
import { formatDate } from '../settings/billingFormat'

export interface AcademicPlanCardProps {
  /** null = the status request failed (the card degrades, the page stays up). */
  academic: AcademicStatus | null
  /** False while a paid Stripe plan is live, or on Enterprise (ADR-042 §6). */
  eligible: boolean
  onSend: (email: string) => Promise<AcademicStatus>
  onVerify: (code: string) => Promise<AcademicStatus>
  /** Refetch the subscription, summary and credits after a successful verify. */
  onVerified: () => void
}

const RESEND_SECONDS = 60
const NOT_ELIGIBLE =
  'To switch to Academic, cancel your paid plan in Manage billing first. You keep it until the period ends.'
const DEAD_CODE = "That code can't be used anymore. Send a new one."

const ERROR_COPY: Record<string, string> = {
  not_academic_email: "That address isn't on our list of academic domains. Use your school email.",
  rate_limited: 'Too many codes requested. Try again in a minute.',
  email_unconfigured: "We can't send verification emails right now. Try again later.",
  email_send_failed: "We couldn't send the email. Try again in a moment.",
  stripe_subscription_active: NOT_ELIGIBLE,
  plan_not_eligible: 'Enterprise plans can’t switch to Academic.',
  academic_email_in_use: 'That address is already verified on another Solus account.',
  code_expired: DEAD_CODE,
  too_many_attempts: 'Too many wrong codes. Wait a while, then send a new one.',
  no_pending_code: DEAD_CODE
}

function errorText(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === 'invalid_code') {
      const detail = error.details?.[0] as { attempts_left?: unknown } | undefined
      const left = typeof detail?.attempts_left === 'number' ? detail.attempts_left : null
      return left === null
        ? "That code didn't match."
        : `That code didn't match — ${left} ${left === 1 ? 'try' : 'tries'} left.`
    }
    const known = ERROR_COPY[error.code]
    if (known) return known
  }
  return 'Something went wrong. Try again.'
}

function suffixHint(suffixes: string[]): string {
  const shown = suffixes.slice(0, 3).map((s) => `.${s}`)
  return `Use your school address — ${shown.join(', ')} and similar.`
}

export function AcademicPlanCard(props: AcademicPlanCardProps): React.JSX.Element {
  const { academic, onVerify } = props
  const active = academic?.state === 'active'
  // Kept here, not in the flow: the page refetch right after a verify swaps the flow for
  // the "Verified …" line, and the confirmation must survive that swap.
  const [justVerified, setJustVerified] = useState(false)
  const verify = async (code: string): Promise<AcademicStatus> => {
    const status = await onVerify(code)
    setJustVerified(true)
    return status
  }
  return (
    <Card
      pad={16}
      role="group"
      aria-label="Academic"
      style={{ marginTop: 12, borderColor: active ? 'var(--acc)' : 'var(--bd)' }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 14, fontWeight: 600 }}>Academic</span>
          <Mono size={9} color="var(--acc)">
            FREE
          </Mono>
        </div>
        {active && (
          <Mono size={9} color="var(--acc)">
            CURRENT PLAN
          </Mono>
        )}
      </div>
      <div style={{ fontSize: 12.5, marginTop: 6 }}>
        Free for students, teachers and researchers.
      </div>
      {academic && (
        <div style={{ fontSize: 11.5, color: 'var(--mut)', marginTop: 4 }}>
          {`Basic limits · ${academic.monthly_credits.toLocaleString()} credits every month · verify once a year`}
        </div>
      )}
      <StepArea {...props} onVerify={verify} justVerified={justVerified} />
    </Card>
  )
}

function StepArea(props: AcademicPlanCardProps & { justVerified: boolean }): React.JSX.Element {
  const { academic, eligible, justVerified } = props
  let body: React.JSX.Element
  if (!academic) body = <Note>Academic verification is unavailable right now.</Note>
  else if (academic.state === 'active') {
    body = (
      <>
        {justVerified && <VerifiedNotice credits={academic.monthly_credits} />}
        <Note>{`Verified ${academic.email} · free until ${formatDate(academic.expires_at)}`}</Note>
      </>
    )
  } else if (!eligible) body = <Note>{NOT_ELIGIBLE}</Note>
  else body = <AcademicFlow {...props} academic={academic} />
  return (
    <div
      role="group"
      aria-label="Academic verification"
      style={{ marginTop: 12, paddingTop: 12, borderTop: '1px solid var(--bd)' }}
    >
      {body}
    </div>
  )
}

function VerifiedNotice({ credits }: { credits: number }): React.JSX.Element {
  return (
    <div role="status" style={{ fontSize: 12.5, marginBottom: 6 }}>
      {`You're on the Academic plan — ${credits.toLocaleString()} credits are in your account.`}
    </div>
  )
}

function Note({ children }: { children: React.ReactNode }): React.JSX.Element {
  return <div style={{ fontSize: 12.5, color: 'var(--mut)', lineHeight: 1.5 }}>{children}</div>
}

function ErrorLine({ id, text }: { id: string; text: string | null }): React.JSX.Element | null {
  if (!text) return null
  return (
    <div id={id} role="alert" style={{ fontSize: 11.5, color: 'var(--err)', marginTop: 6 }}>
      {text}
    </div>
  )
}

const INPUT_STYLE: React.CSSProperties = {
  flex: 1,
  minWidth: 0,
  background: 'var(--bg)',
  color: 'var(--tx)',
  border: '1px solid var(--bd)',
  borderRadius: 3,
  padding: '8px 10px',
  fontSize: 13,
  fontFamily: 'var(--font-ui)',
  outline: 'none'
}

function useCountdown(): [number, () => void] {
  const [left, setLeft] = useState(0)
  useEffect(() => {
    if (left <= 0) return undefined
    const id = window.setTimeout(() => setLeft((n) => n - 1), 1000)
    return () => window.clearTimeout(id)
  }, [left])
  return [left, () => setLeft(RESEND_SECONDS)]
}

type FlowProps = AcademicPlanCardProps & { academic: AcademicStatus }

function AcademicFlow({ academic, onSend, onVerify, onVerified }: FlowProps): React.JSX.Element {
  const [step, setStep] = useState<'email' | 'code' | 'done'>(
    academic.state === 'pending' ? 'code' : 'email'
  )
  const [email, setEmail] = useState(academic.pending_email ?? academic.email ?? '')
  const [sentTo, setSentTo] = useState(academic.pending_email ?? '')
  const [code, setCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [cooldown, startCooldown] = useCountdown()

  async function run(action: () => Promise<void>): Promise<void> {
    setBusy(true)
    setError(null)
    try {
      await action()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  const send = (): Promise<void> =>
    run(async () => {
      const status = await onSend(email.trim())
      setSentTo(status.pending_email ?? email.trim())
      setCode('')
      setStep('code')
      startCooldown()
    })

  const verify = (): Promise<void> =>
    run(async () => {
      await onVerify(code)
      setStep('done')
      onVerified()
    })

  if (step === 'done') return <VerifiedNotice credits={academic.monthly_credits} />
  if (step === 'code') {
    return (
      <CodeStep
        sentTo={sentTo}
        code={code}
        onCode={setCode}
        busy={busy}
        error={error}
        cooldown={cooldown}
        onVerify={() => void verify()}
        onResend={() => void send()}
        onChangeEmail={() => {
          setError(null)
          setStep('email')
        }}
      />
    )
  }
  return (
    <EmailStep
      academic={academic}
      email={email}
      onEmail={setEmail}
      busy={busy}
      error={error}
      onSend={() => void send()}
    />
  )
}

interface EmailStepProps {
  academic: AcademicStatus
  email: string
  onEmail: (value: string) => void
  busy: boolean
  error: string | null
  onSend: () => void
}

function EmailStep({
  academic,
  email,
  onEmail,
  busy,
  error,
  onSend
}: EmailStepProps): React.JSX.Element {
  const canSend = !busy && email.trim().length > 0
  return (
    <>
      {academic.state === 'expired' && (
        <div style={{ fontSize: 12.5, marginBottom: 8 }}>
          {`Your academic plan ended ${formatDate(academic.expires_at)}.`}
        </div>
      )}
      <form
        style={{ display: 'flex', gap: 8 }}
        onSubmit={(e) => {
          e.preventDefault()
          if (canSend) onSend()
        }}
      >
        <input
          aria-label="Academic email"
          type="email"
          autoComplete="email"
          placeholder="you@university.edu"
          value={email}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? 'academic-email-error' : undefined}
          onChange={(e) => onEmail(e.target.value)}
          style={INPUT_STYLE}
        />
        <Button kind="primary" size="sm" type="submit" disabled={!canSend}>
          {busy ? <Spinner size={11} color="var(--acc-ink)" /> : 'Send code'}
        </Button>
      </form>
      <ErrorLine id="academic-email-error" text={error} />
      <div style={{ fontSize: 11, color: 'var(--mut)', marginTop: 6 }}>
        {suffixHint(academic.suffixes)}
      </div>
    </>
  )
}

interface CodeStepProps {
  sentTo: string
  code: string
  onCode: (value: string) => void
  busy: boolean
  error: string | null
  cooldown: number
  onVerify: () => void
  onResend: () => void
  onChangeEmail: () => void
}

function CodeStep(props: CodeStepProps): React.JSX.Element {
  const { sentTo, code, onCode, busy, error, cooldown, onVerify, onResend, onChangeEmail } = props
  const inputRef = useRef<HTMLInputElement>(null)
  useEffect(() => inputRef.current?.focus(), [])
  const canVerify = !busy && code.length === 6
  return (
    <>
      <div style={{ fontSize: 12.5, marginBottom: 8 }}>
        {`We sent a 6-digit code to ${sentTo}. It expires in 15 minutes.`}
      </div>
      <form
        style={{ display: 'flex', gap: 8 }}
        onSubmit={(e) => {
          e.preventDefault()
          if (canVerify) onVerify()
        }}
      >
        <input
          ref={inputRef}
          aria-label="Verification code"
          inputMode="numeric"
          autoComplete="one-time-code"
          maxLength={6}
          value={code}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? 'academic-code-error' : undefined}
          onChange={(e) => onCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
          style={{ ...INPUT_STYLE, fontFamily: 'var(--font-mono)', letterSpacing: '0.2em' }}
        />
        <Button kind="primary" size="sm" type="submit" disabled={!canVerify}>
          {busy ? <Spinner size={11} color="var(--acc-ink)" /> : 'Verify'}
        </Button>
      </form>
      <ErrorLine id="academic-code-error" text={error} />
      <div style={{ display: 'flex', gap: 12, marginTop: 8 }}>
        <Button kind="ghost" size="sm" disabled={busy || cooldown > 0} onClick={onResend}>
          {cooldown > 0 ? `Resend code (${cooldown}s)` : 'Resend code'}
        </Button>
        <Button kind="ghost" size="sm" disabled={busy} onClick={onChangeEmail}>
          Use a different email
        </Button>
      </div>
    </>
  )
}
