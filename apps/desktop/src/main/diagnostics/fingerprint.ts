// SOLUSDEV-311: a stable 16-hex identity for "the same bug" — error name,
// surface and the top stack frames with line/column stripped (so a rebuild
// doesn't split one bug into many), or the digit-normalised message when there
// is no stack. Used for dedupe, the Sentry fingerprint and the `client.error` event.
import { createHash } from 'node:crypto'

const TOP_FRAMES = 5

interface Fingerprintable {
  surface: string
  name: string
  message: string
  stack?: string
}

function frames(stack: string): string[] {
  return stack
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.startsWith('at '))
    .slice(0, TOP_FRAMES)
    .map((line) => line.replace(/:\d+(?::\d+)?\)?$/, ''))
}

export function fingerprintOf(report: Fingerprintable): string {
  const top = report.stack ? frames(report.stack) : []
  const body = top.length > 0 ? top.join('\n') : report.message.replace(/\d+/g, '#')
  return createHash('sha256')
    .update(`${report.name}\n${report.surface}\n${body}`)
    .digest('hex')
    .slice(0, 16)
}
