// Onshape panel links (SOLUS-A7-01). The approval half of the pairing flow.
// SOLUSDEV-318 moved it from Settings to Home › Connected accounts, under
// Onshape's domain tab — a panel link belongs with the Onshape account.
//
// Why this screen is the security boundary: the panel runs inside an Onshape
// iframe and starts with nothing. It shows a code; typing that code HERE, in a
// signed-in Solus session, is the entire proof of who is being linked. The
// Onshape user id Onshape hands the panel is never accepted as identity — it is
// visible to anyone sharing a document, so it can only ever be a label.
import { useCallback, useEffect, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Mono } from '../../components/ui/Mono'
import { listPanelLinks, approvePanelLink, revokePanelLink } from '../../lib/api/resources'
import type { PanelLink } from '../../lib/api/resources'
import { ApiError } from '../../lib/api/envelope.types'
import { Section, Row, InlineError } from '../settings/settingsUi'

/** The catalog id whose domain tab hosts the pairing (accountDomains.ts). */
export const ONSHAPE_PROVIDER = 'onshape'

function approveError(err: unknown): string {
  if (err instanceof ApiError && err.code === 'invalid_pairing') {
    return 'That code is not valid, or it expired. Reload the panel in Onshape for a new one.'
  }
  if (err instanceof ApiError && err.code === 'already_approved') {
    return 'That code was already approved.'
  }
  if (err instanceof ApiError && err.code === 'rate_limited') {
    return 'Too many attempts. Wait a minute and try again.'
  }
  if (err instanceof ApiError && err.code === 'email_not_verified') {
    return 'Verify your email address before linking a panel.'
  }
  return 'Could not link the panel. Please try again.'
}

function used(link: PanelLink): string {
  if (!link.last_used_at) return 'never used'
  return `last used ${new Date(link.last_used_at).toLocaleDateString()}`
}

export function OnshapePanelLinks(): React.JSX.Element {
  const [links, setLinks] = useState<PanelLink[]>([])
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async (): Promise<void> => {
    try {
      setLinks(await listPanelLinks())
    } catch {
      // A settings section that cannot list is not worth an error banner —
      // approving still works, and the list reappears on the next load.
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const onApprove = async (): Promise<void> => {
    setBusy(true)
    setError(null)
    try {
      await approvePanelLink(code.trim().toUpperCase())
      setCode('')
      await refresh()
    } catch (err) {
      setError(approveError(err))
    } finally {
      setBusy(false)
    }
  }

  const onRevoke = async (id: string): Promise<void> => {
    setError(null)
    try {
      await revokePanelLink(id)
    } catch {
      setError('Could not revoke that link. Please try again.')
    }
    await refresh()
  }

  return (
    <Section
      title="Onshape panel"
      sub="Link the Solus panel inside Onshape to this account. Open the panel in an Onshape document, then enter the code it shows."
    >
      <PairingCode code={code} busy={busy} setCode={setCode} onApprove={onApprove} />

      {links.map((link) => (
        <Row
          key={link.id}
          label={
            <span style={{ display: 'inline-flex', gap: 8, alignItems: 'baseline' }}>
              <Mono size={10} color="var(--mut)">
                {link.onshape_user_id ?? 'PANEL'}
              </Mono>
              <span style={{ fontSize: 11.5, color: 'var(--mut)' }}>{used(link)}</span>
            </span>
          }
        >
          <Button kind="ghost" size="sm" onClick={() => void onRevoke(link.id)}>
            Revoke
          </Button>
        </Row>
      ))}

      <InlineError message={error} />
    </Section>
  )
}

function PairingCode({
  code,
  busy,
  setCode,
  onApprove
}: {
  code: string
  busy: boolean
  setCode: (value: string) => void
  onApprove: () => Promise<void>
}): React.JSX.Element {
  return (
    <Row label="Pairing code">
      <span style={{ display: 'inline-flex', gap: 8, alignItems: 'center' }}>
        <input
          aria-label="Pairing code"
          value={code}
          placeholder="ABCD-EFGH"
          maxLength={16}
          onChange={(e) => setCode(e.target.value)}
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 12,
            letterSpacing: '1px',
            textTransform: 'uppercase',
            padding: '6px 8px',
            width: 130,
            background: 'var(--sur2)',
            border: '1px solid var(--bd)',
            borderRadius: 4,
            color: 'inherit'
          }}
        />
        <Button
          size="sm"
          disabled={busy || code.trim().length < 4}
          onClick={() => void onApprove()}
        >
          {busy ? 'Linking…' : 'Link panel'}
        </Button>
      </span>
    </Row>
  )
}
