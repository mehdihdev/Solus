// SOLUSDEV-235 — detail › Overview: what the extension adds, its activity in
// this project, and the requires / credits / links cards.
import { Card } from '../../../components/ui/Card'
import { Icons, type IconName } from '../../../components/ui/icons.constants'
import { KV } from '../../../components/ui/KV'
import { Mono } from '../../../components/ui/Mono'
import { SectionLabel } from '../ExtensionCard'
import { SOURCE_KIND_DESCRIPTION } from '../extensionLogic'
import type { ContributionKind, ExtensionView, SourceKind } from '../extension.types'

const CONTRIBUTION_ICON: Readonly<Record<ContributionKind, IconName>> = {
  widget: 'grid',
  grounding: 'sol',
  check: 'check',
  panel: 'lines'
}

const RIGHT_COLUMN_WIDTH = 260

export function OverviewTab({ view }: { view: ExtensionView }): React.JSX.Element {
  return (
    <div style={{ display: 'flex', gap: 20, alignItems: 'flex-start' }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <SectionLabel>WHAT IT ADDS</SectionLabel>
        {view.manifest.contributions.map((c) => {
          const Icon = Icons[CONTRIBUTION_ICON[c.kind]]
          return (
            <div
              key={c.title}
              style={{
                display: 'flex',
                gap: 12,
                padding: '12px 0',
                borderBottom: '1px solid var(--bd)'
              }}
            >
              <span style={{ color: 'var(--acc)', marginTop: 2 }}>
                <Icon size={13} />
              </span>
              <div>
                <div style={{ fontSize: 13, fontWeight: 600 }}>{c.title}</div>
                <div style={{ fontSize: 12, color: 'var(--mut)', marginTop: 2, lineHeight: 1.5 }}>
                  {c.detail}
                </div>
              </div>
            </div>
          )
        })}

        <SectionLabel>IN THIS PROJECT</SectionLabel>
        <ActivityCard view={view} />
      </div>

      <div
        style={{
          width: RIGHT_COLUMN_WIDTH,
          flexShrink: 0,
          display: 'flex',
          flexDirection: 'column',
          gap: 12,
          marginTop: 22
        }}
      >
        <RequiresCard view={view} />
        <CreditsCard view={view} />
        <LinksCard view={view} />
      </div>
    </div>
  )
}

/** No backend reports extension runs yet, so activity is derived from install
 *  state alone — an honest status, never a fabricated timeline. */
function ActivityCard({ view }: { view: ExtensionView }): React.JSX.Element {
  const { state } = view
  const [status, text] = !state.installed
    ? ['NOT INSTALLED', 'Install to see its activity here.']
    : !state.enabled
      ? ['DISABLED', 'Turned off in this project.']
      : ['IDLE', 'No activity in this project yet.']
  return (
    <Card pad={14}>
      <Mono size={9.5} color="var(--tx)">
        {status}
      </Mono>
      <div style={{ fontSize: 12, color: 'var(--mut)', marginTop: 6 }}>{text}</div>
    </Card>
  )
}

function RequiresCard({ view }: { view: ExtensionView }): React.JSX.Element {
  const { requires } = view.manifest
  const isMissing = (group: readonly SourceKind[]): boolean => view.missing.includes(group)
  return (
    <Card pad={14} data-testid="detail-requires">
      <Mono size={9.5}>REQUIRES</Mono>
      {requires.length === 0 ? (
        <div style={{ fontSize: 12, color: 'var(--mut)', marginTop: 8 }}>
          No connected source required.
        </div>
      ) : (
        requires.map((group) => {
          const met = !isMissing(group)
          return (
            <div
              key={group.join('|')}
              data-met={met}
              style={{ display: 'flex', gap: 8, alignItems: 'flex-start', marginTop: 8 }}
            >
              <span
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: 99,
                  marginTop: 5,
                  flexShrink: 0,
                  background: met ? 'var(--ok)' : 'var(--warn)'
                }}
              />
              <span style={{ fontSize: 12, lineHeight: 1.45 }}>
                {group.map((k) => SOURCE_KIND_DESCRIPTION[k]).join(' or ')}
              </span>
            </div>
          )
        })
      )}
    </Card>
  )
}

function CreditsCard({ view }: { view: ExtensionView }): React.JSX.Element {
  const { credits } = view.manifest
  return (
    <Card pad={14}>
      <Mono size={9.5}>CREDITS</Mono>
      <div style={{ marginTop: 4 }}>
        <KV k="This cycle" v={String(credits.thisCycle)} />
        <KV k="Per run, typical" v={credits.perRun === null ? 'none' : `~${credits.perRun}`} />
      </div>
    </Card>
  )
}

function LinksCard({ view }: { view: ExtensionView }): React.JSX.Element {
  const { links } = view.manifest
  const rows: ReadonlyArray<{ label: string; href?: string }> = [
    { label: 'Documentation', href: links.documentation },
    { label: 'Source', href: links.source },
    { label: 'Report an issue', href: links.issues }
  ]
  return (
    <Card pad={14}>
      <Mono size={9.5}>LINKS</Mono>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 8 }}>
        {rows
          .filter((r): r is { label: string; href: string } => Boolean(r.href))
          .map((r) => (
            // Catalog URLs are Solus-authored https constants (enforced by the
            // catalog test); main's window-open handler routes them to the OS browser.
            <a
              key={r.label}
              href={r.href}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 5,
                fontSize: 12.5,
                color: 'var(--acc)',
                textDecoration: 'none'
              }}
            >
              {r.label} <Icons.external size={10} />
            </a>
          ))}
      </div>
    </Card>
  )
}
