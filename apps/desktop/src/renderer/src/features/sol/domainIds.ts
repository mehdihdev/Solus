// The SOL page's token readers (design template): a graph entity's domain maps onto the four
// ADR-027 colour tokens; a citation token `[connector:target]` maps only when its connector is one
// we know — otherwise no dot, never a fabricated colour — and names the surface it opens. Plain
// functions, kept out of domainDot.tsx so that file exports components only (react-refresh).
import type { DomainId } from '../../theme/tokens.constants'

const DOMAIN_IDS: Readonly<Record<string, DomainId>> = {
  code: 'sw',
  electrical: 'ee',
  mechanical: 'me',
  runtime: 'rt',
  simulation: 'rt'
}

const CONNECTOR_DOMAINS: Readonly<Record<string, DomainId>> = {
  github: 'sw',
  gitlab: 'sw',
  ros: 'sw',
  kicad: 'ee',
  altium: 'ee',
  onshape: 'me',
  fusion: 'me',
  solidworks: 'me',
  mujoco: 'rt',
  isaac: 'rt',
  gazebo: 'rt'
}

export function domainIdOf(domain: string): DomainId | null {
  return DOMAIN_IDS[domain] ?? null
}

const CITATION = /^\[([^:\]]+):([^\]]+)\]$/

/** The connector's domain for a `[connector:target]` citation, or null. */
export function citationDomain(token: string): DomainId | null {
  const match = CITATION.exec(token)
  return match ? (CONNECTOR_DOMAINS[match[1].toLowerCase()] ?? null) : null
}

/** The surface a citation opens (SOLUSDEV-321 P7): `[entity:<id>]` a graph entity the Workspace
 *  focuses, `[finding:<id>]` a finding the Findings pane opens, `[solus:<section>:<id>]` a `.solus`
 *  entry. Read from the message's server-verified `citations` alone, never from prose. */
export type CitationTarget =
  | { kind: 'entity'; id: string }
  | { kind: 'finding'; id: string }
  | { kind: 'solus'; section: string; id: string }

const SOLUS_REF = /^([^:]+):(.+)$/

/** The surface `token` opens, or null: every other connector is a plain chip. */
export function citationTarget(token: string): CitationTarget | null {
  const match = CITATION.exec(token)
  if (!match) return null
  const [, connector, ref] = match
  if (connector === 'entity' || connector === 'finding') return { kind: connector, id: ref }
  const solus = connector === 'solus' ? SOLUS_REF.exec(ref) : null
  return solus ? { kind: 'solus', section: solus[1], id: solus[2] } : null
}
