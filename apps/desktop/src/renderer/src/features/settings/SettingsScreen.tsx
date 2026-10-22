// Settings screen (SOLUSDEV-86 / SOLUS-FND-06; design A in SOLUSDEV-318): a
// sidebar (find, Needs attention, sections grouped You / Workspace / System)
// beside one scrolling page. Local prefs (SOL desktop rows, appearance, How
// you engineer, About) always render; account, plan, tools, team and privacy
// need a live connection (dev bypass shows a sign-in prompt instead of
// fabricated data). Billing, team members and tool accounts are managed on
// their own screens — Settings summarises them and links out.
import './settings.css'
import { useMemo, useState } from 'react'
import { settingsStagger } from './settingsMotion'
import { useActiveSection } from './useActiveSection'
import { Card } from '../../components/ui/Card'
import { SolusLogo } from '../../components/ui/SolusLogo'
import { Spinner } from '../../components/ui/Spinner'
import { useSettingsData, type SettingsData } from './useSettingsData'
import { useTeamData, type TeamData } from '../team/useTeamData'
import { useAccountConnections } from '../workspace/useAccountConnections'
import { useShellStore, type MainScreen } from '../workspace/shellStore'
import type { HomePaneView } from '../workspace/HomeAccountNav'
import { useOfflineReason } from '../workspace/workspaceOnline'
import { getDesktopExtensionsBridge, getDesktopSolBridge } from '../../lib/desktopBridge'
import { PreferencesCard } from '../preferences/PreferencesCard'
import { SettingsNav } from './SettingsNav'
import {
  ATTENTION_ANCHOR,
  SETTINGS_SECTIONS,
  filterSections,
  sectionAnchor,
  type SectionId
} from './settingsSections.constants'
import { attentionItems, type AttentionItem } from './attention'
import { useDesktopSol, type DesktopSol } from './useDesktopSol'
import { useCredits, type CreditsView } from './useCredits'
import { AttentionSection, type AttentionActions } from './sections/AttentionSection'
import { ProfileSection } from './sections/ProfileSection'
import { SolSection } from './sections/SolSection'
import { AppearanceSection } from './sections/AppearanceSection'
import { PlanSection } from './sections/PlanSection'
import { ToolsSection } from './sections/ToolsSection'
import { TeamSection } from './sections/TeamSection'
import { PrivacySection } from './sections/PrivacySection'
import { DeveloperSection } from './sections/DeveloperSection'
import { AboutSection } from './sections/AboutSection'

function OfflineNotice(): React.JSX.Element {
  const reason = useOfflineReason()
  return (
    <Card pad={20}>
      <div style={{ fontSize: 12.5, color: 'var(--mut)', lineHeight: 1.55 }}>
        {reason === 'api_unreachable'
          ? "You're signed in, but Solus can't reach its API — profile, plan, connected tools, team and privacy need it. SOL, appearance and About still work."
          : 'Sign in to Solus to manage your profile, plan, connected tools, team and privacy. SOL, appearance and About are available offline.'}
      </div>
    </Card>
  )
}

function scrollTo(anchor: string): void {
  document.getElementById(anchor)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

interface PageContext {
  settings: SettingsData
  team: TeamData
  accounts: ReturnType<typeof useAccountConnections>
  sol: DesktopSol
  credits: CreditsView
  navigate: (screen: MainScreen) => void
  openHome: (view: HomePaneView) => void
}

/** One renderer per section id — the page order is SETTINGS_SECTIONS'. */
const SECTION_RENDERERS: Readonly<Record<SectionId, (ctx: PageContext) => React.JSX.Element>> = {
  profile: (ctx) => <ProfileSection data={ctx.settings} />,
  sol: (ctx) => (
    <SolSection data={ctx.settings} sol={ctx.sol} onFixCapture={() => scrollTo(ATTENTION_ANCHOR)} />
  ),
  // HOME H3 (SOLUSDEV-244) lives here since SOLUSDEV-253: the one part of
  // ~/.solus the user owns, machine-local, read by SOL on every turn.
  engineer: () => (
    <div id={sectionAnchor('engineer')} style={{ scrollMarginTop: 16 }}>
      <PreferencesCard />
    </div>
  ),
  appearance: () => <AppearanceSection />,
  plan: (ctx) => (
    <PlanSection
      subscription={ctx.settings.subscription}
      credits={ctx.credits}
      onOpenBilling={() => ctx.navigate('billing')}
    />
  ),
  tools: (ctx) => (
    <ToolsSection
      status={ctx.accounts.status}
      connections={ctx.accounts.connections}
      onManage={() => ctx.openHome('accounts')}
    />
  ),
  team: (ctx) => <TeamSection team={ctx.team} onOpenTeam={() => ctx.openHome('members')} />,
  privacy: (ctx) => <PrivacySection data={ctx.settings} />,
  developer: () => <DeveloperSection />,
  about: () => <AboutSection />
}

/** Which sections exist right now — the sidebar lists exactly these. */
function applicableSections(ctx: PageContext, desktop: boolean): ReadonlySet<SectionId> {
  const online = ctx.settings.status === 'ready'
  const ids: SectionId[] = ['sol', 'engineer', 'appearance', 'about']
  if (online) ids.push('profile', 'plan', 'privacy')
  if (online && ctx.accounts.status !== 'offline') ids.push('tools')
  if (ctx.team.status === 'ready' && ctx.team.team) ids.push('team')
  // Developer mode (SOLUSDEV-235 §4) loads folders through main, so it exists
  // only under the desktop app — the browser preview never sees the section.
  if (desktop) ids.push('developer')
  return new Set(ids)
}

function attentionActions(ctx: PageContext): AttentionActions {
  return {
    openCaptureSettings: ctx.sol.openCaptureSettings,
    recheckCapture: ctx.sol.recheck,
    turnOffCapture: () => ctx.sol.apply((b) => b.setScreenIntelligence(false)),
    openBilling: () => ctx.navigate('billing'),
    openAccounts: () => ctx.openHome('accounts')
  }
}

/** Everything the page reads, plus the shell navigation it links out with. */
function useSettingsPage(onNavigate?: (screen: MainScreen) => void): {
  ctx: PageContext
  items: AttentionItem[]
} {
  const settings = useSettingsData()
  const team = useTeamData()
  const accounts = useAccountConnections()
  const [solBridge] = useState(getDesktopSolBridge)
  const sol = useDesktopSol(solBridge)
  const online = settings.status === 'ready'
  const credits = useCredits(online)
  const navigate = (screen: MainScreen): void => onNavigate?.(screen)
  const openHome = (view: HomePaneView): void => {
    useShellStore.getState().requestHomeView(view)
    navigate('home')
  }
  const items = useMemo(
    () =>
      attentionItems({
        sol: sol.state,
        subscription: online ? settings.subscription : null,
        connections: online ? accounts.connections : []
      }),
    [sol.state, online, settings.subscription, accounts.connections]
  )
  return { ctx: { settings, team, accounts, sol, credits, navigate, openHome }, items }
}

export interface SettingsScreenProps {
  /** Shell navigation (Billing, Home). Absent in isolated renders. */
  onNavigate?: (screen: MainScreen) => void
}

export function SettingsScreen({ onNavigate }: SettingsScreenProps = {}): React.JSX.Element {
  const { ctx, items } = useSettingsPage(onNavigate)
  const [query, setQuery] = useState('')
  const applicable = applicableSections(ctx, getDesktopExtensionsBridge() !== null)
  const visible = filterSections(
    SETTINGS_SECTIONS.filter((s) => applicable.has(s.id)),
    query
  )
  const activeAnchor = useActiveSection(visible.map((s) => sectionAnchor(s.id)))

  if (ctx.settings.status === 'loading') {
    return (
      <div
        style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
        data-testid="settings-loading"
      >
        <Spinner size={20} />
      </div>
    )
  }

  return (
    <div className="settings-page" style={{ flex: 1, overflowY: 'auto', minWidth: 0 }}>
      <div style={PAGE}>
        <div className="settings-sidebar" style={SIDEBAR}>
          {/* Brand row (SOLUSDEV-233): the Solus logo beside the title. */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <SolusLogo size={26} />
            <h1 style={{ margin: 0, fontSize: 20, fontWeight: 600, letterSpacing: '-0.015em' }}>
              Settings
            </h1>
          </div>
          <SettingsNav
            sections={visible}
            query={query}
            onQuery={setQuery}
            attentionCount={query ? 0 : items.length}
            activeId={visible.find((s) => sectionAnchor(s.id) === activeAnchor)?.id ?? null}
            onJump={(id) => scrollTo(id === 'attention' ? ATTENTION_ANCHOR : sectionAnchor(id))}
          />
        </div>
        <main aria-label="Settings" style={CONTENT}>
          {!query && <AttentionSection items={items} actions={attentionActions(ctx)} />}
          {/* Keyed by id: a section that comes back from a filter eases in again. */}
          {visible.map((s, i) => (
            <div key={s.id} className="settings-section-in" style={settingsStagger(i)}>
              {SECTION_RENDERERS[s.id](ctx)}
            </div>
          ))}
          {ctx.settings.status !== 'ready' && <OfflineNotice />}
        </main>
      </div>
    </div>
  )
}

// Design A layout: the sidebar wraps above the page at narrow widths.
const PAGE: React.CSSProperties = {
  maxWidth: 1080,
  margin: '0 auto',
  padding: '22px 24px 48px',
  display: 'flex',
  flexWrap: 'wrap',
  gap: 28,
  alignItems: 'flex-start'
}
const SIDEBAR: React.CSSProperties = {
  flex: '1 1 200px',
  maxWidth: 220,
  display: 'flex',
  flexDirection: 'column',
  gap: 16
}
const CONTENT: React.CSSProperties = {
  flex: '999 1 520px',
  minWidth: 0,
  display: 'flex',
  flexDirection: 'column',
  gap: 14
}
