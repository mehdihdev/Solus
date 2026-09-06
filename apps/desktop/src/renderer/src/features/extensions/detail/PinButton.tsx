// SOLUSDEV-246 / STORE ST3 — "Pin for all projects" from the detail header: the
// same account-level pin the rail's right-click menu sets. Pinning installs
// nothing; the tab shows in every project, honest about where it is installed.
import { useState } from 'react'
import { Button } from '../../../components/ui/Button'
import { usePinsStore } from '../pinsStore'

export function PinButton({ slug }: { slug: string }): React.JSX.Element {
  const pinned = usePinsStore((s) => s.pins.some((p) => p.slug === slug))
  const [busy, setBusy] = useState(false)
  const [refused, setRefused] = useState(false)
  const toggle = async (): Promise<void> => {
    setBusy(true)
    const store = usePinsStore.getState()
    const ok = await (pinned ? store.unpin(slug) : store.pin(slug))
    setBusy(false)
    setRefused(!ok)
  }
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
      {refused && (
        <span role="status" style={{ fontSize: 11.5, color: 'var(--warn)' }}>
          Couldn&apos;t change the pin.
        </span>
      )}
      <Button
        kind="soft"
        size="sm"
        disabled={busy}
        aria-pressed={pinned}
        title={
          pinned
            ? 'Remove this extension’s tab from your other projects'
            : 'Show this extension’s tab in every project you open'
        }
        onClick={() => void toggle()}
      >
        {pinned ? 'Pinned for all projects' : 'Pin for all projects'}
      </Button>
    </span>
  )
}
