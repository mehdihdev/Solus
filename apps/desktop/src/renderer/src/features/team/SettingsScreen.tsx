// Settings screen. Appearance / SOL mode / integrations are wired to their real
// stores. Profile and the team/workspace section load live data when the
// workspace is linked to the API (real name, team rename, project-notify
// toggle, delete-team), and fall back to the prototype static rendering when
// offline (dev bypass), ported from SettingsScreen in TestDesign/app.
import { useState, type ReactNode } from 'react'
import { Avatar } from '../../components/ui/Avatar'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { KV } from '../../components/ui/KV'
import { Mono } from '../../components/ui/Mono'
import { Segmented } from '../../components/ui/Segmented'
import {
  SOLUS_ACCENTS,
  SOLUS_THEMES,
  type AccentId,
  type ThemeId
} from '../../theme/tokens.constants'
import { useSettingsStore } from '../../store/settingsStore'
import { useOnboardingStore } from '../onboarding/onboardingStore'
import { INTEGRATIONS } from '../onboarding/integrations.constants'
import { FALLBACK_PROJECT_NAME } from '../workspace/workspaceData.constants'
import { displayName, useMe, type Identity } from '../workspace/useMe'
import { useTeamData, type TeamData } from './useTeamData'

const USAGE_USED = 1840
const USAGE_TOTAL = 5000
const USAGE_ROWS: readonly (readonly [string, number])[] = [
  ['Cross-domain checks', 940],
  ['SOL conversations', 612],
  ['Bench anomaly watch', 288]
]

const THEME_IDS = Object.keys(SOLUS_THEMES) as readonly ThemeId[]
const ACCENT_IDS = Object.keys(SOLUS_ACCENTS) as readonly AccentId[]
const SOL_MODES = ['Guide', 'Expert'] as const
const DENSITIES = ['compact', 'regular'] as const
const NOTIFY_OPTIONS = ['On', 'Off'] as const

interface SectionProps {
  title: string
  sub?: string
  children: ReactNode
}

function Section({ title, sub, children }: SectionProps): React.JSX.Element {
  return (
    <Card pad={20} style={{ marginBottom: 14 }}>
      <div style={{ fontSize: 14, fontWeight: 600 }}>{title}</div>
      {sub && (
        <div style={{ fontSize: 11.5, color: 'var(--mut)', marginTop: 3, lineHeight: 1.5 }}>
          {sub}
        </div>
      )}
      <div style={{ marginTop: 14 }}>{children}</div>
    </Card>
  )
}

interface RowProps {
  label: ReactNode
  children: ReactNode
}

function Row({ label, children }: RowProps): React.JSX.Element {
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        gap: 16,
        padding: '9px 0',
        borderBottom: '1px solid var(--bd)'
      }}
    >
      <span style={{ fontSize: 12.5 }}>{label}</span>
      <div>{children}</div>
    </div>
  )
}

function ProfileSection({ me }: { me: Identity }): React.JSX.Element {
  const live = me.status === 'ready'
  const name = live ? displayName(me.name, me.email) : 'Maya Krishnan'
  const detail = live ? me.email : 'maya@strider.dev · Firmware · workspace owner'
  return (
    <Section title="Profile">
      <div style={{ display: 'flex', gap: 14, alignItems: 'center' }}>
        <Avatar name={name} size={42} />
        <div>
          <div style={{ fontSize: 13.5, fontWeight: 600 }}>{name}</div>
          <div style={{ fontSize: 11.5, color: 'var(--mut)' }}>{detail}</div>
        </div>
      </div>
    </Section>
  )
}

function AppearanceSection(): React.JSX.Element {
  const theme = useSettingsStore((s) => s.theme)
  const accent = useSettingsStore((s) => s.accent)
  const density = useSettingsStore((s) => s.density)
  const setTheme = useSettingsStore((s) => s.setTheme)
  const setAccent = useSettingsStore((s) => s.setAccent)
  const setDensity = useSettingsStore((s) => s.setDensity)
  return (
    <Section
      title="Appearance"
      sub="Theme presets include editor schemes — set Solus to match your IDE."
    >
      <Row label="Theme">
        <select
          value={theme}
          onChange={(e) => setTheme(e.target.value as ThemeId)}
          style={{
            background: 'var(--bg)',
            color: 'var(--tx)',
            border: '1px solid var(--bd)',
            borderRadius: 3,
            padding: '6px 10px',
            fontSize: 12,
            fontFamily: 'var(--font-ui)',
            outline: 'none'
          }}
        >
          {THEME_IDS.map((k) => (
            <option key={k} value={k}>
              {SOLUS_THEMES[k].name}
            </option>
          ))}
        </select>
      </Row>
      <Row label="Accent">
        <div style={{ display: 'flex', gap: 8 }}>
          {ACCENT_IDS.map((k) => (
            <button
              key={k}
              type="button"
              aria-label={`Accent ${k}`}
              onClick={() => setAccent(k)}
              style={{
                width: 22,
                height: 22,
                borderRadius: 99,
                background: SOLUS_ACCENTS[k].c,
                cursor: 'pointer',
                border: accent === k ? '2px solid var(--tx)' : '2px solid transparent',
                boxSizing: 'border-box',
                padding: 0
              }}
            ></button>
          ))}
        </div>
      </Row>
      <Row label="Density">
        <Segmented
          size="sm"
          ariaLabel="Density"
          options={DENSITIES}
          value={density}
          onChange={setDensity}
        />
      </Row>
    </Section>
  )
}

function UsageSection(): React.JSX.Element {
  return (
    <Section title="Usage" sub="SOL meters AI reasoning by credit. Resets on the 1st.">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 18 }}>
          {USAGE_USED.toLocaleString()}
          <span style={{ fontSize: 11, color: 'var(--mut)' }}>
            {' '}
            / {USAGE_TOTAL.toLocaleString()} credits
          </span>
        </span>
        <Mono size={9.5}>TEAM PLAN</Mono>
      </div>
      <div
        style={{
          height: 6,
          background: 'var(--bg)',
          border: '1px solid var(--bd)',
          borderRadius: 99,
          marginTop: 10,
          overflow: 'hidden'
        }}
      >
        <div
          style={{
            width: (USAGE_USED / USAGE_TOTAL) * 100 + '%',
            height: '100%',
            background: 'var(--acc)'
          }}
        ></div>
      </div>
      <div style={{ marginTop: 12 }}>
        {USAGE_ROWS.map(([k, v]) => (
          <KV key={k} k={k} v={v.toLocaleString() + ' cr'} />
        ))}
      </div>
    </Section>
  )
}

function IntegrationsSection(): React.JSX.Element {
  const connections = useOnboardingStore((s) => s.connections)
  return (
    <Section title="Integrations">
      {INTEGRATIONS.map((i) => (
        <Row
          key={i.id}
          label={
            <span style={{ display: 'inline-flex', gap: 10, alignItems: 'center' }}>
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 10.5,
                  width: 26,
                  height: 26,
                  borderRadius: 3,
                  background: 'var(--sur2)',
                  border: '1px solid var(--bd)',
                  display: 'inline-flex',
                  alignItems: 'center',
                  justifyContent: 'center'
                }}
              >
                {i.mark}
              </span>
              {i.name}
            </span>
          }
        >
          {connections[i.id]?.phase === 'done' ? (
            <Mono size={9} color="var(--ok)">
              ● CONNECTED
            </Mono>
          ) : (
            <Mono size={9} color="var(--mut)">
              ○ NOT CONNECTED
            </Mono>
          )}
        </Row>
      ))}
    </Section>
  )
}

function TeamNameRow({
  team,
  canRename,
  onRename
}: {
  team: TeamData['team']
  canRename: boolean
  onRename: (name: string) => void
}): React.JSX.Element {
  const [name, setName] = useState(team?.name ?? '')
  if (!canRename) {
    return <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>{team?.name}</span>
  }
  return (
    <span style={{ display: 'inline-flex', gap: 8 }}>
      <input
        aria-label="Team name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        style={{
          background: 'var(--bg)',
          color: 'var(--tx)',
          border: '1px solid var(--bd)',
          borderRadius: 3,
          padding: '6px 10px',
          fontSize: 12,
          fontFamily: 'var(--font-ui)',
          outline: 'none'
        }}
      />
      <Button kind="ghost" size="sm" onClick={() => onRename(name.trim())}>
        Save
      </Button>
    </span>
  )
}

function DeleteTeamRow({ onDelete }: { onDelete: () => void }): React.JSX.Element {
  const [confirming, setConfirming] = useState(false)
  if (!confirming) {
    return (
      <Button kind="danger" size="sm" onClick={() => setConfirming(true)}>
        Delete team
      </Button>
    )
  }
  return (
    <span style={{ display: 'inline-flex', gap: 8, alignItems: 'center' }}>
      <span style={{ fontSize: 11.5, color: 'var(--mut)' }}>Delete this team?</span>
      <Button kind="ghost" size="sm" onClick={() => setConfirming(false)}>
        Cancel
      </Button>
      <Button kind="danger" size="sm" onClick={onDelete}>
        Delete team
      </Button>
    </span>
  )
}

/** Live team settings: rename, project-notify toggle, delete (owner only). */
function TeamSettingsSection({ data }: { data: TeamData }): React.JSX.Element {
  const { team, myRole, actions } = data
  const notify = team?.settings.notify_project_created ?? true
  const canRename = myRole === 'owner' || myRole === 'admin'
  const showDanger = myRole === 'owner' && team !== null && !team.is_personal

  return (
    <Section title="Team" sub="Shared with everyone on this team.">
      <Row label="Name">
        <TeamNameRow
          team={team}
          canRename={canRename}
          onRename={(name) => void actions.updateTeam({ name })}
        />
      </Row>
      <Row label="Notify team on new projects">
        <Segmented
          size="sm"
          ariaLabel="Notify on new projects"
          options={NOTIFY_OPTIONS}
          value={notify ? 'On' : 'Off'}
          onChange={(v) =>
            void actions.updateTeam({ settings: { notify_project_created: v === 'On' } })
          }
        />
      </Row>
      {showDanger && (
        <Row label="Danger zone">
          <DeleteTeamRow onDelete={() => void actions.deleteTeam()} />
        </Row>
      )}
    </Section>
  )
}

function WorkspaceDemoSection(): React.JSX.Element {
  return (
    <Section title="Workspace">
      <Row label="Name">
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>
          {FALLBACK_PROJECT_NAME}
        </span>
      </Row>
      <Row label="Danger zone">
        <Button kind="danger" size="sm">
          Delete workspace
        </Button>
      </Row>
    </Section>
  )
}

export function SettingsScreen(): React.JSX.Element {
  const solMode = useSettingsStore((s) => s.solMode)
  const setSolMode = useSettingsStore((s) => s.setSolMode)
  const me = useMe()
  const team = useTeamData()

  return (
    <div style={{ flex: 1, overflowY: 'auto', minWidth: 0 }}>
      <div style={{ maxWidth: 680, margin: '0 auto', padding: '22px 24px 48px' }}>
        <h1
          style={{ margin: '0 0 18px', fontSize: 22, fontWeight: 600, letterSpacing: '-0.015em' }}
        >
          Settings
        </h1>

        <ProfileSection me={me} />

        <Section title="SOL" sub="How the agent talks to you.">
          <Row label="Answer mode">
            <Segmented
              size="sm"
              ariaLabel="Answer mode"
              options={SOL_MODES}
              value={solMode}
              onChange={setSolMode}
            />
          </Row>
        </Section>

        <UsageSection />
        <AppearanceSection />
        <IntegrationsSection />

        {team.status === 'ready' ? <TeamSettingsSection data={team} /> : <WorkspaceDemoSection />}
      </div>
    </div>
  )
}
