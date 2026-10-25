// SOLUSDEV-320 P4-T1 — one hover sentence per edge, built only from what the
// relation already carries (type, names, evidence, confirmation/confidence).
// Pure: never a model call. `docs/architecture/workspace-navigation.md`.
import { isCandidate } from '@solus/shared-types'
import type { Entity, Relation } from '../../../lib/api/resources'

const MAX_LENGTH = 240

export interface EdgeEvidence {
  kind: string
  ref: string
  detail: string | null
}

/** `snake_case` → words, for relation types, origins and evidence kinds. */
export const relationWords = (value: string): string => value.replaceAll('_', ' ')
const words = relationWords

/** `properties.evidence` narrowed item by item; anything malformed is dropped. */
export function edgeEvidence(properties: Record<string, unknown> | undefined): EdgeEvidence[] {
  const raw = properties?.evidence
  if (!Array.isArray(raw)) return []
  return raw.flatMap((item) => {
    if (typeof item !== 'object' || item === null) return []
    const { kind, ref, detail } = item as Record<string, unknown>
    if (typeof kind !== 'string') return []
    return [
      {
        kind,
        ref: typeof ref === 'string' ? ref : '',
        detail: typeof detail === 'string' && detail ? detail : null
      }
    ]
  })
}

function status({ properties, origin, confidence }: Relation): string | null {
  const confirmed = properties?.confirmed_at
  if (typeof confirmed === 'string' && confirmed) return `confirmed ${confirmed.slice(0, 10)}`
  if (isCandidate(origin, confidence)) return `inferred, ${Math.round((confidence ?? 0) * 100)}%`
  return origin ? words(origin) : null
}

/** `"<from> <type> <to>, because <detail> (<kind> <ref>; …, confirmed <date>)"`, ≤ 240 chars. */
export function edgeSentence(
  relation: Relation,
  from: Entity | undefined,
  to: Entity | undefined
): string {
  const evidence = edgeEvidence(relation.properties)
  const details = evidence.flatMap((item) => (item.detail ? [item.detail] : []))
  const refs = evidence.map((item) => `${words(item.kind)} ${item.ref}`.trim())
  const tail = status(relation)
  const parenthetical = [refs.join('; '), tail].filter(Boolean).join(', ')
  const sentence =
    `${from?.name ?? relation.from_entity_id} ${words(relation.type)} ${to?.name ?? relation.to_entity_id}` +
    (details.length ? `, because ${details.join('; ')}` : '') +
    (parenthetical ? ` (${parenthetical})` : '')
  return sentence.length > MAX_LENGTH ? `${sentence.slice(0, MAX_LENGTH - 1)}…` : sentence
}
