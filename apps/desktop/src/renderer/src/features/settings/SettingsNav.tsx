// The Settings sidebar (SOLUSDEV-318, design A): "Find a setting", the
// Needs-attention entry, and the sections grouped You / Workspace / System.
// Entries are buttons that scroll the page — never `#hash` links, which the
// HashRouter would read as a route.
import { Icons } from '../../components/ui/icons.constants'
import { Mono } from '../../components/ui/Mono'
import { Reveal } from './Reveal'
import {
  SECTION_GROUPS,
  type SectionId,
  type SettingsSectionDef
} from './settingsSections.constants'

export interface SettingsNavProps {
  /** The sections the page shows (already filtered by the query). */
  sections: readonly SettingsSectionDef[]
  query: string
  onQuery: (query: string) => void
  attentionCount: number
  /** The section scrolled into view (scroll-spy); highlighted in the list. */
  activeId?: SectionId | null
  onJump: (id: SectionId | 'attention') => void
}

const ITEM: React.CSSProperties = {
  display: 'block',
  width: '100%',
  textAlign: 'left',
  padding: '6px 10px',
  borderRadius: 3,
  border: 'none',
  background: 'transparent',
  color: 'var(--mut)',
  fontSize: 12.5,
  fontFamily: 'var(--font-ui)'
}

function SearchBox({
  query,
  onQuery
}: Pick<SettingsNavProps, 'query' | 'onQuery'>): React.JSX.Element {
  return (
    <label
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        background: 'var(--sur)',
        border: '1px solid var(--bd)',
        borderRadius: 4,
        padding: '6px 10px',
        color: 'var(--mut)'
      }}
    >
      <Icons.search size={13} />
      <input
        type="search"
        aria-label="Find a setting"
        placeholder="Find a setting"
        value={query}
        onChange={(e) => onQuery(e.target.value)}
        style={{
          flex: 1,
          minWidth: 0,
          border: 'none',
          outline: 'none',
          background: 'transparent',
          color: 'var(--tx)',
          fontSize: 12,
          fontFamily: 'var(--font-ui)'
        }}
      />
    </label>
  )
}

function AttentionEntry({
  count,
  onJump
}: {
  count: number
  onJump: () => void
}): React.JSX.Element {
  return (
    <button
      type="button"
      onClick={onJump}
      className="interactive"
      style={{
        ...ITEM,
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        padding: '8px 10px',
        color: 'var(--tx)',
        fontWeight: 500,
        background: 'color-mix(in srgb, var(--warn) 12%, var(--sur))',
        border: '1px solid color-mix(in srgb, var(--warn) 40%, var(--bd))'
      }}
    >
      Needs attention
      <span
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 11,
          background: 'var(--warn)',
          color: 'var(--acc-ink)',
          borderRadius: 99,
          padding: '1px 7px'
        }}
      >
        {/* While the entry collapses out the count is 0: show nothing, not "0". */}
        {count > 0 ? count : ''}
      </span>
    </button>
  )
}

export function SettingsNav({
  sections,
  query,
  onQuery,
  attentionCount,
  activeId = null,
  onJump
}: SettingsNavProps): React.JSX.Element {
  return (
    <nav
      aria-label="Settings sections"
      style={{ display: 'flex', flexDirection: 'column', gap: 16 }}
    >
      <SearchBox query={query} onQuery={onQuery} />
      <Reveal open={attentionCount > 0}>
        <AttentionEntry count={attentionCount} onJump={() => onJump('attention')} />
      </Reveal>
      {sections.length === 0 && (
        <div style={{ fontSize: 12, color: 'var(--mut)', padding: '0 10px' }}>
          No settings match “{query.trim()}”.
        </div>
      )}
      {SECTION_GROUPS.map((group) => {
        const items = sections.filter((s) => s.group === group)
        if (items.length === 0) return null
        return (
          <div key={group} style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
            <Mono
              size={9.5}
              color="var(--mut)"
              style={{ padding: '0 10px 4px', letterSpacing: '0.12em' }}
            >
              {group}
            </Mono>
            {items.map((s) => (
              <button
                key={s.id}
                type="button"
                className="interactive settings-nav-item"
                aria-current={activeId === s.id ? 'true' : undefined}
                onClick={() => onJump(s.id)}
                style={ITEM}
              >
                {s.title}
              </button>
            ))}
          </div>
        )
      })}
    </nav>
  )
}
