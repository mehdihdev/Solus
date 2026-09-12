// S1-W3 ratchet: model identity lives ONLY in the backend's models.yaml. No
// renderer/main/preload source may name one — the UI shows `sol-reasoner-1`
// and an effort label, so a model swap on the server is invisible here.
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { describe, expect, it } from 'vitest'

const SRC_ROOT = join(__dirname, '..', '..', '..', '..')
const MODEL_NAME = /(claude|gemini)-[\w.-]*\d|gpt-\d/i
// Test-only canned API data (imported by *.test.ts only) — not product source.
const ALLOWLIST = new Set(['renderer/src/features/sourcing/testing/fixtures.ts'])

function* sources(dir: string): Generator<string> {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) {
      if (name !== 'node_modules') yield* sources(path)
    } else if (/\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name)) {
      yield path
    }
  }
}

describe('no model names in desktop source', () => {
  it('finds only allowlisted files naming a model', () => {
    const offenders = [...sources(SRC_ROOT)]
      .map((path) => relative(SRC_ROOT, path))
      .filter((rel) => !ALLOWLIST.has(rel))
      .filter((rel) => MODEL_NAME.test(readFileSync(join(SRC_ROOT, rel), 'utf8')))
    expect(offenders).toEqual([])
  })
})
