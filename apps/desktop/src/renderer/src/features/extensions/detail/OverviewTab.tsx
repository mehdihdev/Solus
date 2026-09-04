// SOLUSDEV-235 — detail › Overview: what the extension adds (from its manifest
// views), its status in this project, and the requires / credits / links cards.
import { Card } from '../../../components/ui/Card'
import { Icons, type IconName } from '../../../components/ui/icons.constants'
import { KV } from '../../../components/ui/KV'
import { Mono } from '../../../components/ui/Mono'
import { SectionLabel } from '../ExtensionCard'
import { contributionsOf, isSafeExternalUrl, SOURCE_KIND_DESCRIPTION } from '../extensionLogic'
import type { Contribution, ExtensionView, SourceKind } from '../extension.types'

const CONTRIBUTION_ICON: Readonly<Record<Contribution['kind'], IconName>> = {
  widget: 'grid',
  page: 'lines',
  window: 'box',
  permissions: 'check'
}

const RIGHT_COLUMN_WIDTH = 260

export function OverviewTab({ view }: { view: ExtensionView }): React.JSX.Element {
  return (
    <div style={{ display: 'flex', gap: 20, alignItems: 'flex-start' }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <SectionLabel>WHAT IT ADDS</SectionLabel>
        {contributionsOf(view).map((c) => {
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
        {view.manifest === null && (
          <div style={{ fontSize: 12, color: 'var(--mut)', padding: '10px 0' }}>
            Loading the extension’s manifest…
          </div>
        )}

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
        <CreditsCard />
        <LinksCard view={view} />
      </div>
    </div>
  )
}

/** No backend reports extension runs yet, so activity is derived from the
 *  install row alone — an honest status, never a fabricated timeline. */
function ActivityCard({ view }: { view: ExtensionView }): React.JSX.Element {
  const { state } = view
  const [status, text] = !state.installed
    ? ['NOT INSTALLED', 'Install to see its activity here.']
    : state.blocked
      ? ['BLOCKED BY TEAM', 'An owner blocked this extension for your team.']
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
  const { requires } = view.catalog
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

/** Credit-denominated (ADR-018). Spend is not metered per extension yet, so the
 *  only honest value is a dash — never a fabricated number. */
function CreditsCard(): React.JSX.Element {
  return (
    <Card pad={14}>
      <Mono size={9.5}>CREDITS</Mono>
      <div style={{ marginTop: 4 }}>
        <KV k="This cycle" v="—" />
      </div>
    </Card>
  )
}

function LinksCard({ view }: { view: ExtensionView }): React.JSX.Element {
  const links = view.manifest?.store.links ?? {}
  const rows = [
    { label: 'Documentation', href: links.documentation },
    { label: 'Terms', href: links.terms },
    { label: 'Report an issue', href: links.issues }
  ].filter((r): r is { label: string; href: string } => isSafeExternalUrl(r.href))
  return (
    <Card pad={14}>
      <Mono size={9.5}>LINKS</Mono>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 8 }}>
        {rows.length === 0 && (
          <div style={{ fontSize: 12, color: 'var(--mut)' }}>No links published.</div>
        )}
        {rows.map((r) => (
          // Manifest URLs are developer input: only https survives
          // `isSafeExternalUrl`; main's window-open handler routes them to the OS browser.
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
