// SOLUSDEV-168 — the `@` token under the caret, as pure text arithmetic.
//
// Deliberately separate from the composer and from any fetching: what counts as
// a mention token is the fiddly part (an email address is not one; a token ends
// at a space; the caret's token is not always the last one in the string), and
// it is far easier to get right against a table of cases than through a
// rendered input.
//
// The composer keeps the picked ids in a list beside the text — this module
// only decides what the user is currently typing at, and how to splice a chosen
// name back in.

/** The `@…` the caret currently sits inside. Offsets are into the full text. */
export interface MentionToken {
  /** The text after `@`, up to the caret. Empty for a bare `@`. */
  query: string
  /** Index of the `@` itself. */
  start: number
  /** Index just past the last character of the token (i.e. the caret). */
  end: number
}

/** Longer than any name worth typing; a "token" past this is prose, not a search. */
const MAX_TOKEN = 64

export function activeMentionToken(text: string, caret: number): MentionToken | null {
  const start = text.lastIndexOf('@', Math.max(0, caret - 1))
  if (start < 0) return null

  // An `@` glued to the previous word is an email address or a handle, not a
  // mention the user is opening.
  if (start > 0 && !/\s/.test(text[start - 1])) return null

  const query = text.slice(start + 1, caret)
  // Whitespace closes the token: the mention was picked or abandoned.
  if (/\s/.test(query)) return null
  if (query.length > MAX_TOKEN) return null

  return { query, start, end: caret }
}

/** Splice a chosen entity's name over the token, leaving one trailing space. */
export function replaceMentionToken(
  text: string,
  token: MentionToken,
  name: string
): { text: string; caret: number } {
  const after = text.slice(token.end)
  const spacer = after.startsWith(' ') ? '' : ' '
  const replacement = `@${name}${spacer}`
  return {
    text: `${text.slice(0, token.start)}${replacement}${after}`,
    caret: token.start + replacement.length
  }
}

/**
 * Mirrors `reason.MAX_ANCHORS` on the server, which caps `MessageCreate.mentions`
 * and re-applies the same bound in `plan_query`. Duplicated across the process
 * boundary because it must be; the composer trims to it so a request cannot 422.
 */
export const MAX_MENTIONS = 8

/** An entity the user has actually picked from the list. */
export interface PickedMention {
  id: string
  name: string
}
