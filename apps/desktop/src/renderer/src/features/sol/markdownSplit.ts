// SOLUSDEV-252 S2: split a streaming markdown reply into the SETTLED prefix
// (blocks that are complete and will never change again) and the TAIL (the
// block still being written). SolMarkdown parses the two separately, so a
// token only re-parses the current block instead of the whole reply.
//
// Pure line scan — no markdown parser here. A boundary is a blank line that is
// not inside a fenced code block and does not sit between two items of the
// same (loose) list; tables end at a blank line by definition, so they are
// never cut mid-run.
// ponytail: fences are only recognised at ≤3 spaces of indent (CommonMark's
// top-level rule) — a fence nested inside a list item or blockquote is not
// tracked; the block is then simply split later than ideal, never wrongly.

export interface SplitResult {
  settled: string
  tail: string
}

const FENCE_OPEN = /^ {0,3}(`{3,}|~{3,})(.*)$/
const LIST_ITEM = /^ {0,3}(?:[-*+]|\d{1,9}[.)])(?:\s|$)/
const LIST_CONTINUATION = /^ {2,}\S/
/** A row is any line opening with `|`; a separator is `|` then only `-`, `:`, `|`, space. */
const TABLE_ROW = /^\|/
const TABLE_SEPARATOR = /^\|[\s:|-]*-[\s:|-]*$/
/** Only backticks/tildes on the line — a fence opener still being typed (or a bare one). */
const FENCE_STUB = /^ {0,3}(?:`+|~+)\s*$/

function fenceOpener(line: string): string | null {
  const m = FENCE_OPEN.exec(line)
  if (!m) return null
  // A backtick fence's info string may not contain a backtick (CommonMark).
  if (m[1][0] === '`' && m[2].includes('`')) return null
  return m[1]
}

function closesFence(line: string, opener: string): boolean {
  const m = /^ {0,3}(`{3,}|~{3,})\s*$/.exec(line)
  return m !== null && m[1][0] === opener[0] && m[1].length >= opener.length
}

function isListLine(line: string): boolean {
  return LIST_ITEM.test(line) || LIST_CONTINUATION.test(line)
}

function nextNonBlank(lines: readonly string[], from: number): string | undefined {
  for (let i = from; i < lines.length; i++) if (lines[i].trim() !== '') return lines[i]
  return undefined
}

export function splitSettled(content: string): SplitResult {
  const lines = content.split('\n')
  let fence: string | null = null
  let inList = false
  let settledEnd = 0
  let pos = 0
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    pos += line.length + 1
    if (fence) {
      if (closesFence(line, fence)) fence = null
      continue
    }
    if (line.trim() === '') {
      const next = nextNonBlank(lines, i + 1)
      // A blank between two list lines is a loose list, not a boundary.
      if (inList && next !== undefined && isListLine(next)) continue
      inList = false
      settledEnd = Math.min(pos, content.length)
      continue
    }
    const opener = fenceOpener(line)
    if (opener) {
      fence = opener
      inList = false
      continue
    }
    inList = isListLine(line)
  }
  return { settled: content.slice(0, settledEnd), tail: content.slice(settledEnd) }
}

/** The tail with a flip-prone last line held back: a table row before the
 *  header separator exists (paragraph ↔ table toggle) or a fence opener still
 *  being typed (stray backtick run ↔ code block). */
export function stableTail(tail: string): string {
  const lines = tail.split('\n')
  if (lines[lines.length - 1] === '') lines.pop()
  if (lines.length === 0) return ''
  const last = lines[lines.length - 1]
  const hold = fenceOpen(lines)
    ? false // inside a code block every line is literal; a bare ``` is the closer
    : FENCE_STUB.test(last) || (TABLE_ROW.test(last) && !tableEstablished(lines))
  return hold ? lines.slice(0, -1).join('\n') : tail
}

/** True when a fence opened in `lines` is still open before the last line. */
function fenceOpen(lines: readonly string[]): boolean {
  let fence: string | null = null
  for (let i = 0; i < lines.length - 1; i++) {
    if (fence) {
      if (closesFence(lines[i], fence)) fence = null
    } else fence = fenceOpener(lines[i])
  }
  return fence !== null
}

/** True when the run of `|` lines ending BEFORE the last line already holds a separator. */
function tableEstablished(lines: readonly string[]): boolean {
  for (let i = lines.length - 2; i >= 0 && TABLE_ROW.test(lines[i]); i--) {
    if (TABLE_SEPARATOR.test(lines[i])) return true
  }
  return false
}
