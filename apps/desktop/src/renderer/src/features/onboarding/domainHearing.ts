// SOLUSDEV-323: which of the four worlds a project description mentions — the
// Project step's "worlds I'm hearing" chips and the Connect step's suggestions
// (docs/wireflows/onboarding.md). A keyword heuristic, presented as hearing,
// never as analysis: nothing here reaches a model or the graph. Pure.

export type Domain = 'sw' | 'ee' | 'me' | 'rt'

export interface DomainMeta {
  readonly key: Domain
  readonly label: string
  /** The domain's CSS token (house domain colours). */
  readonly color: string
}

export const DOMAINS: readonly DomainMeta[] = [
  { key: 'sw', label: 'Software', color: 'var(--sw)' },
  { key: 'ee', label: 'Electrical', color: 'var(--ee)' },
  { key: 'me', label: 'Mechanical', color: 'var(--me)' },
  { key: 'rt', label: 'Runtime', color: 'var(--rt)' }
]

export type HeardDomains = Readonly<Record<Domain, boolean>>

const KEYWORDS: Readonly<Record<Domain, readonly string[]>> = {
  sw: [
    'firmware',
    'code',
    'software',
    'python',
    'rust',
    'embedded',
    'jetson',
    'stm32',
    'arduino',
    'esp32',
    'github',
    'gitlab',
    'app'
  ],
  ee: [
    'pcb',
    'kicad',
    'altium',
    'schematic',
    'schematics',
    'circuit',
    'board',
    'bldc',
    'driver',
    'drivers',
    'sensor',
    'sensors',
    'imu',
    'battery',
    'bms',
    'power',
    'can'
  ],
  me: [
    'cad',
    'onshape',
    'chassis',
    'frame',
    'enclosure',
    'arm',
    'leg',
    'legs',
    'gripper',
    'gearbox',
    'mount',
    'dof',
    'joint',
    'joints',
    'printed'
  ],
  rt: ['ros', 'ros2', 'telemetry', 'sim', 'simulation', 'teleop', 'runtime', 'servo', 'servos']
}

const PATTERNS: Readonly<Record<Domain, RegExp>> = {
  sw: wordPattern(KEYWORDS.sw),
  ee: wordPattern(KEYWORDS.ee),
  me: wordPattern(KEYWORDS.me),
  rt: wordPattern(KEYWORDS.rt)
}

function wordPattern(words: readonly string[]): RegExp {
  return new RegExp(`\\b(?:${words.join('|')})\\b`, 'i')
}

/** Which worlds the description mentions (whole words, any case). */
export function hearDomains(text: string): HeardDomains {
  return {
    sw: PATTERNS.sw.test(text),
    ee: PATTERNS.ee.test(text),
    me: PATTERNS.me.test(text),
    rt: PATTERNS.rt.test(text)
  }
}

export function heardCount(heard: HeardDomains): number {
  return DOMAINS.filter((d) => heard[d.key]).length
}

const INTEGRATION_DOMAINS: Readonly<Record<string, Domain>> = {
  github: 'sw',
  gitlab: 'sw',
  kicad: 'ee',
  altium: 'ee',
  onshape: 'me',
  ros: 'rt'
}

/** The world a connector feeds, or null when it has none we know of. */
export function domainForIntegration(id: string): Domain | null {
  return INTEGRATION_DOMAINS[id] ?? null
}

/** Catalog ids to suggest: the first connector of each heard world, in catalog order. */
export function suggestedIntegrations(ids: readonly string[], heard: HeardDomains): string[] {
  const taken = new Set<Domain>()
  return ids.filter((id) => {
    const domain = domainForIntegration(id)
    if (!domain || !heard[domain] || taken.has(domain)) return false
    taken.add(domain)
    return true
  })
}
