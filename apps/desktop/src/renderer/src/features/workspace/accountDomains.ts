// Home's connected-accounts card groups every tool by the engineering domain
// it serves (SOLUSDEV-244): Mechanical, Electrical, Simulation, Software. The
// live registry does not yet declare a domain per connector, so the
// classification lives here, keyed by provider type, with an explicit
// fallback — a tool the backend grows that is not listed lands under Software
// rather than vanishing from the card. Pure, so the words are testable
// without rendering.
import type { CatalogEntry } from '../onboarding/integrationCatalog'

export const ACCOUNT_DOMAINS = ['mechanical', 'electrical', 'simulation', 'software'] as const
export type AccountDomain = (typeof ACCOUNT_DOMAINS)[number]

export const ACCOUNT_DOMAIN_LABEL: Readonly<Record<AccountDomain, string>> = {
  mechanical: 'Mechanical',
  electrical: 'Electrical',
  simulation: 'Simulation',
  software: 'Software'
}

const DOMAIN_BY_PROVIDER: Readonly<Record<string, AccountDomain>> = {
  onshape: 'mechanical',
  fusion: 'mechanical',
  solidworks: 'mechanical',
  autocad: 'mechanical',
  kicad: 'electrical',
  altium: 'electrical',
  mujoco: 'simulation',
  isaac: 'simulation',
  gazebo: 'simulation',
  webots: 'simulation',
  github: 'software',
  gitlab: 'software',
  ros: 'software'
}

/** The tab a catalog tool belongs under. */
export function accountDomain(entry: Pick<CatalogEntry, 'id'>): AccountDomain {
  return DOMAIN_BY_PROVIDER[entry.id.toLowerCase()] ?? 'software'
}

/** What an empty tab says — plain, never a fake row. */
export function emptyDomainText(domain: AccountDomain): string {
  return `No ${ACCOUNT_DOMAIN_LABEL[domain].toLowerCase()} tools are available to connect yet.`
}
