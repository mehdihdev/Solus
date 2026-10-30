// Domain dots for the SOL page (design template): a graph entity's domain maps onto
// the four ADR-027 colour tokens; a citation token `[connector:target]` maps only when
// its connector is one we know — otherwise no dot. Never a fabricated colour.
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

/** `[entity:<id>]` names a graph entity the Workspace can focus; anything else does not. */
export function citationEntityId(token: string): string | null {
  const match = CITATION.exec(token)
  return match && match[1] === 'entity' ? match[2] : null
}

export function DomainDot({
  d,
  size = 6
}: {
  d: DomainId | null
  size?: number
}): React.JSX.Element | null {
  if (!d) return null
  return (
    <span
      aria-hidden="true"
      style={{
        display: 'inline-block',
        width: size,
        height: size,
        borderRadius: '50%',
        flex: 'none',
        background: `var(--${d})`
      }}
    />
  )
}
