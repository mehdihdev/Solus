// Settings sidebar index (SOLUSDEV-318, design A): every section, its sidebar
// group, and the words "Find a setting" matches on. The screen renders sections
// in this order; filtering hides both the nav entry and the section.
export const SECTION_GROUPS = ['You', 'Workspace', 'System'] as const
export type SectionGroup = (typeof SECTION_GROUPS)[number]

export type SectionId =
  | 'profile'
  | 'sol'
  | 'engineer'
  | 'appearance'
  | 'plan'
  | 'tools'
  | 'team'
  | 'privacy'
  | 'developer'
  | 'about'

export interface SettingsSectionDef {
  readonly id: SectionId
  readonly title: string
  readonly group: SectionGroup
  readonly keywords: readonly string[]
}

export const SETTINGS_SECTIONS: readonly SettingsSectionDef[] = [
  { id: 'profile', title: 'Profile', group: 'You', keywords: ['name', 'email', 'avatar'] },
  {
    id: 'sol',
    title: 'SOL',
    group: 'You',
    keywords: [
      'answer mode',
      'action mode',
      'guide',
      'expert',
      'build',
      'screen',
      'capture',
      'ctrl',
      'gestures'
    ]
  },
  {
    id: 'engineer',
    title: 'How you engineer',
    group: 'You',
    keywords: ['conventions', 'code style', 'units', 'standards', 'documentation']
  },
  {
    id: 'appearance',
    title: 'Appearance',
    group: 'You',
    keywords: ['theme', 'accent', 'color', 'dark', 'light']
  },
  {
    id: 'plan',
    title: 'Plan & usage',
    group: 'Workspace',
    keywords: ['billing', 'credits', 'trial', 'subscription', 'upgrade', 'seats', 'limits']
  },
  {
    id: 'tools',
    title: 'Connected tools',
    group: 'Workspace',
    keywords: ['integrations', 'accounts', 'github', 'onshape', 'kicad', 'sources', 'reconnect']
  },
  {
    id: 'team',
    title: 'Team',
    group: 'Workspace',
    keywords: ['members', 'rename', 'notifications', 'roles']
  },
  {
    id: 'privacy',
    title: 'Privacy & data',
    group: 'System',
    keywords: ['usage data', 'consent', 'collection', 'delete account']
  },
  {
    id: 'developer',
    title: 'Developer',
    group: 'System',
    keywords: ['extensions', 'unpacked', 'dev']
  },
  {
    id: 'about',
    title: 'About & legal',
    group: 'System',
    keywords: ['version', 'terms', 'privacy policy', 'contact', 'support', 'legal']
  }
]

/** The DOM id a section anchors on (the sidebar scrolls to it). */
export function sectionAnchor(id: SectionId | 'attention'): string {
  return `settings-${id}`
}

export const ATTENTION_ANCHOR = sectionAnchor('attention')

/** Sections whose title or keywords contain the query (case-insensitive). */
export function filterSections(
  sections: readonly SettingsSectionDef[],
  query: string
): readonly SettingsSectionDef[] {
  const q = query.trim().toLowerCase()
  if (!q) return sections
  return sections.filter(
    (s) => s.title.toLowerCase().includes(q) || s.keywords.some((k) => k.includes(q))
  )
}
