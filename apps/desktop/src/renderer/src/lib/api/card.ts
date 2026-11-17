// SOLUSDEV-326: the one check that a value is the action-gate contract's Card
// (docs/contracts/action-gate.md §Cards). A card crosses a process boundary on the open-card
// route, the `tool_confirmation` frame and the confirmations list; one that is not this shape is
// not drawn (the server skips such rows too).
import { CARD_KINDS, type Card } from '@solus/shared-types'

type Row = Record<string, unknown>
export const isRow = (value: unknown): value is Row => typeof value === 'object' && value !== null
export const isText = (value: unknown): value is string => typeof value === 'string'
const isTextOrNull = (value: unknown): boolean => value === null || isText(value)

function isField(value: unknown): boolean {
  return value === null || (isRow(value) && isText(value.label) && isText(value.value))
}

export function isCard(value: unknown): value is Card {
  return (
    isRow(value) &&
    (CARD_KINDS as readonly unknown[]).includes(value.kind) &&
    [value.title, value.body, value.primary, value.receipt].every(isText) &&
    isTextOrNull(value.more) &&
    isTextOrNull(value.secondary) &&
    isField(value.field) &&
    typeof value.resumes === 'boolean'
  )
}

/** The tool whose row is a question, not a parked call (action-gate contract §Cards 5). */
export const QUESTION_TOOL = 'ask_user'

/** A card body cut at its `backtick` pairs: the odd pieces are the insides, drawn as code chips;
 *  a lone backtick stays text. Card text is model-authored, so the pieces print as text nodes. */
export const splitChips = (body: string): string[] => body.split(/`([^`]+)`/)

/** What the person typed over the card's field, or null when it stands as SOL wrote it. */
export function fieldEdit(field: Card['field'], value: string): string | null {
  const typed = value.trim()
  return field && typed && typed !== field.value.trim() ? typed : null
}
