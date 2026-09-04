// SOLUSDEV-235 / EXT-20 — Settings → Developer (extensions-runtime wireflow §4,
// architecture §7): load an unpacked extension folder, see main's validation
// problems verbatim, reload or remove. Main is the only validator and the only
// writer of the durable registration; this surface renders the renderer-side
// mirror (devExtensionsStore) and asks the OS folder picker through the folder
// bridge. Desktop-only — without the extensions bridge it renders nothing, so
// the browser preview never offers a picker it cannot open.
import { useCallback, useEffect, useState } from 'react'
import { Button } from '../../../components/ui/Button'
import { Mono } from '../../../components/ui/Mono'
import { getDesktopExtensionsBridge, getDesktopFolderBridge } from '../../../lib/desktopBridge'
import {
  useDevExtensionsStore,
  type DevExtensionEntry,
  type DevLoadOutcome
} from '../../devExtensions/devExtensionsStore'
import { DevBadge } from '../../extensions/pageview/PageHeader'
import { Section } from '../settingsUi'

const SUB =
  'Load an unpacked extension folder to test it in this project. Dev extensions never publish and show a DEV badge everywhere.'
const EMPTY = 'No unpacked extensions loaded.'
const REMOVE_FAILED = 'Could not remove that extension. Please try again.'

/** A load that main attributed to no registration: shown under the button. */
interface Notice {
  readonly path: string | null
  readonly problems: readonly string[]
}

function ProblemList({ problems }: { problems: readonly string[] }): React.JSX.Element | null {
  if (problems.length === 0) return null
  return (
    <ul
      style={{
        margin: '6px 0 0',
        paddingLeft: 16,
        fontSize: 11.5,
        lineHeight: 1.5,
        color: 'var(--err)',
        fontFamily: 'var(--font-mono)'
      }}
    >
      {problems.map((problem, i) => (
        <li key={`${i}:${problem}`}>{problem}</li>
      ))}
    </ul>
  )
}

function LoadNotice({ notice }: { notice: Notice | null }): React.JSX.Element | null {
  if (notice === null) return null
  return (
    <div role="alert" style={{ marginTop: 10, fontSize: 11.5, color: 'var(--err)' }}>
      {notice.path === null ? 'Not loaded.' : `${notice.path} — not loaded`}
      <ProblemList problems={notice.problems} />
    </div>
  )
}

interface RowProps {
  readonly slug: string
  readonly entry: DevExtensionEntry
  readonly busy: boolean
  readonly onReload: () => void
  readonly onPick: () => void
  readonly onRemove: () => void
}

function DevExtensionRow({
  slug,
  entry,
  busy,
  onReload,
  onPick,
  onRemove
}: RowProps): React.JSX.Element {
  const name = entry.manifest?.extension.name ?? null
  return (
    <div
      className="screen-in"
      data-testid={`dev-ext-${slug}`}
      style={{ padding: '10px 0', borderBottom: '1px solid var(--bd)' }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
        {name === null ? (
          <span style={{ fontSize: 12.5, color: 'var(--err)' }}>Not loaded</span>
        ) : (
          <span style={{ fontSize: 12.5, fontWeight: 600 }}>{name}</span>
        )}
        <DevBadge />
        <Mono size={9.5}>{slug}</Mono>
        <span style={{ flex: 1 }} />
        {name === null ? (
          <Button size="sm" onClick={onPick} disabled={busy}>
            Pick again
          </Button>
        ) : (
          <Button size="sm" onClick={onReload} disabled={busy}>
            Reload
          </Button>
        )}
        <Button size="sm" kind="danger" onClick={onRemove} disabled={busy}>
          Remove
        </Button>
      </div>
      <div
        title={entry.devPath}
        style={{
          marginTop: 3,
          fontSize: 11,
          color: 'var(--mut)',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap'
        }}
      >
        {entry.devPath}
      </div>
      <ProblemList problems={entry.problems} />
    </div>
  )
}

/** Only an unattributed failure needs the notice; attributed ones sit on their row. */
function noticeFor(path: string, outcome: DevLoadOutcome): Notice | null {
  return outcome.ok || outcome.slug !== null ? null : { path, problems: outcome.problems }
}

export function DeveloperSection(): React.JSX.Element | null {
  const entries = useDevExtensionsStore((s) => s.entries)
  const hydrate = useDevExtensionsStore((s) => s.hydrate)
  const load = useDevExtensionsStore((s) => s.load)
  const reload = useDevExtensionsStore((s) => s.reload)
  const remove = useDevExtensionsStore((s) => s.remove)
  const [notice, setNotice] = useState<Notice | null>(null)
  const [busy, setBusy] = useState(false)
  const hasBridge = getDesktopExtensionsBridge() !== null

  useEffect(() => {
    if (hasBridge) void hydrate()
  }, [hasBridge, hydrate])

  const run = useCallback(async (task: () => Promise<Notice | null>): Promise<void> => {
    setBusy(true)
    try {
      setNotice(await task())
    } finally {
      setBusy(false)
    }
  }, [])

  const onPick = (): Promise<void> =>
    run(async () => {
      const path = (await getDesktopFolderBridge()?.pick()) ?? null
      if (path === null) return null
      return noticeFor(path, await load(path))
    })
  const onReload = (slug: string): Promise<void> =>
    run(async () => {
      const outcome = await reload(slug)
      return outcome.ok || outcome.slug !== null ? null : { path: null, problems: outcome.problems }
    })
  const onRemove = (slug: string): Promise<void> =>
    run(async () => ((await remove(slug)) ? null : { path: null, problems: [REMOVE_FAILED] }))

  if (!hasBridge) return null
  const slugs = Object.keys(entries).sort()
  return (
    <Section title="Developer" sub={SUB}>
      <Button kind="soft" size="sm" onClick={() => void onPick()} disabled={busy}>
        Load unpacked extension…
      </Button>
      <LoadNotice notice={notice} />
      <div style={{ marginTop: 12 }}>
        {slugs.length === 0 && (
          <div style={{ fontSize: 12, color: 'var(--mut)', padding: '6px 0' }}>{EMPTY}</div>
        )}
        {slugs.map((slug) => (
          <DevExtensionRow
            key={slug}
            slug={slug}
            entry={entries[slug]}
            busy={busy}
            onReload={() => void onReload(slug)}
            onPick={() => void onPick()}
            onRemove={() => void onRemove(slug)}
          />
        ))}
      </div>
    </Section>
  )
}
