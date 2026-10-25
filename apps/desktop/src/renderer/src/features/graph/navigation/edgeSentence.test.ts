// SOLUSDEV-320 P4-T1 — the hover sentence is built from the relation alone:
// type, the two names, evidence refs and the confirmation/confidence tail.
// Never a model call; bounded length.
import { describe, expect, it } from 'vitest'
import type { Entity, Relation } from '../../../lib/api/resources'
import { edgeSentence } from './edgeSentence'

const entity = (id: string, name: string): Entity => ({
  id,
  name,
  type: 'part',
  domain: 'electrical',
  source_key: id
})
const relation = (overrides: Partial<Relation> = {}): Relation => ({
  id: 'r1',
  type: 'commands',
  from_entity_id: 'code',
  to_entity_id: 'motor',
  ...overrides
})
const code = entity('code', 'firmware.ino:42')
const motor = entity('motor', 'Follower-Motor-3')

describe('edgeSentence', () => {
  it('reads type, names, evidence detail, evidence refs and the confirmation date', () => {
    const sentence = edgeSentence(
      relation({
        properties: {
          evidence: [
            {
              kind: 'firmware_symbol',
              ref: 'firmware.ino:42',
              detail: 'the code writes to bus address 3'
            },
            { kind: 'bus_enumeration', ref: '' }
          ],
          confirmed_at: '2026-09-14T10:12:00Z'
        }
      }),
      code,
      motor
    )
    expect(sentence).toBe(
      'firmware.ino:42 commands Follower-Motor-3, because the code writes to bus address 3 ' +
        '(firmware symbol firmware.ino:42; bus enumeration, confirmed 2026-09-14)'
    )
  })

  it('falls back to ids and shows a candidate as inferred with its confidence', () => {
    expect(edgeSentence(relation({ origin: 'inferred', confidence: 0.7 }), undefined, motor)).toBe(
      'code commands Follower-Motor-3 (inferred, 70%)'
    )
  })

  it('names a non-candidate origin and copes with no properties at all', () => {
    expect(edgeSentence(relation({ type: 'reads_from', origin: 'connector' }), code, motor)).toBe(
      'firmware.ino:42 reads from Follower-Motor-3 (connector)'
    )
    expect(edgeSentence(relation({ type: 'wires' }), code, motor)).toBe(
      'firmware.ino:42 wires Follower-Motor-3'
    )
  })

  it('ignores malformed evidence and bounds the length with an ellipsis', () => {
    const detail = 'x'.repeat(400)
    const sentence = edgeSentence(
      relation({
        properties: { evidence: [{ kind: 'netlist', ref: 'NET1', detail }, 'junk', null] }
      }),
      code,
      motor
    )
    expect(sentence.length).toBe(240)
    expect(sentence.endsWith('…')).toBe(true)
    expect(sentence.startsWith('firmware.ino:42 commands Follower-Motor-3, because xxx')).toBe(true)
  })
})
