// Account danger zone (SOLUSDEV-82): permanent account deletion. Surfaces the
// 409 ownership-transfer block; on success tears down the session like sign-out.
import { useState } from 'react'
import { Button } from '../../../components/ui/Button'
import { deleteMe } from '../../../lib/api/resources'
import { ApiError } from '../../../lib/api/envelope.types'
import { useAuthStore } from '../../../store/authStore'
import { useWorkspaceStore } from '../../../store/workspaceStore'
import { Section, Row, InlineError } from '../settingsUi'

function deleteAccountError(err: unknown): string {
  if (err instanceof ApiError && err.code === 'ownership_transfer_required') {
    const n = err.details?.length ?? 0
    return `You solely own ${n} shared team${n === 1 ? '' : 's'}. Transfer ownership (Team → member roles) before deleting your account.`
  }
  if (err instanceof ApiError && err.code === 'email_not_verified') {
    return 'Verify your email address before deleting your account.'
  }
  return 'Could not delete your account. Please try again.'
}

export function AccountSection(): React.JSX.Element {
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const onConfirm = async (): Promise<void> => {
    setBusy(true)
    setError(null)
    try {
      await deleteMe()
    } catch (err) {
      setBusy(false)
      setError(deleteAccountError(err))
      return
    }
    // Durable teardown: sign out + clear workspace. Flipping auth to
    // unauthenticated re-routes the app to the landing page (RootRoute).
    await useAuthStore.getState().signOut()
    useWorkspaceStore.getState().reset()
  }

  return (
    <Section title="Account" sub="Permanently delete your account and personal data.">
      <Row label="Danger zone">
        {!confirming ? (
          <Button kind="danger" size="sm" onClick={() => setConfirming(true)}>
            Delete account
          </Button>
        ) : (
          <span style={{ display: 'inline-flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <span style={{ fontSize: 11.5, color: 'var(--mut)' }}>
              This permanently deletes your account. This cannot be undone.
            </span>
            <Button
              kind="ghost"
              size="sm"
              onClick={() => {
                setConfirming(false)
                setError(null)
              }}
            >
              Cancel
            </Button>
            <Button kind="danger" size="sm" disabled={busy} onClick={() => void onConfirm()}>
              {busy ? 'Deleting…' : 'Delete account'}
            </Button>
          </span>
        )}
      </Row>
      <InlineError message={error} />
    </Section>
  )
}
