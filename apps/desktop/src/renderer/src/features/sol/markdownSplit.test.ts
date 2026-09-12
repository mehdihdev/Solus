// SOLUSDEV-252 S2: the settled/tail split behind the two-parse SolMarkdown.
// `splitSettled` picks the last block boundary that is safe to freeze;
// `stableTail` holds back a last line whose meaning would flip mid-token.
import { describe, it, expect } from 'vitest'
import { splitSettled, stableTail } from './markdownSplit'
import { buildBenchMarkdown, splitIntoTokens } from './streamBench'

describe('splitSettled', () => {
  it('empty input → nothing settled, nothing in the tail', () => {
    expect(splitSettled('')).toEqual({ settled: '', tail: '' })
  })

  it('no blank line at all → everything is tail', () => {
    const content = 'one line\nsecond line still the same paragraph'
    expect(splitSettled(content)).toEqual({ settled: '', tail: content })
  })

  it('settles at the last blank-line boundary, blank line included', () => {
    expect(splitSettled('# Title\n\nfirst para\n\nsecond para')).toEqual({
      settled: '# Title\n\nfirst para\n\n',
      tail: 'second para'
    })
  })

  it('a trailing blank line settles everything', () => {
    expect(splitSettled('para\n\n')).toEqual({ settled: 'para\n\n', tail: '' })
  })

  it('does not split inside an open fenced code block (blank lines are code)', () => {
    const content = 'intro\n\n```c\nint a;\n\nint b;\n'
    expect(splitSettled(content)).toEqual({
      settled: 'intro\n\n',
      tail: '```c\nint a;\n\nint b;\n'
    })
  })

  it('splits after a closed fence once a blank line follows it', () => {
    const content = 'intro\n\n```c\nint a;\n\nint b;\n```\n\nafter'
    expect(splitSettled(content)).toEqual({
      settled: 'intro\n\n```c\nint a;\n\nint b;\n```\n\n',
      tail: 'after'
    })
  })

  it('tracks ~~~ fences and does not let a shorter inner ``` close a longer outer fence', () => {
    const tilde = 'a\n\n~~~\nx\n\ny\n'
    expect(splitSettled(tilde).settled).toBe('a\n\n')
    const nested = 'a\n\n````md\n```\ncode\n```\n\nstill inside\n'
    expect(splitSettled(nested).settled).toBe('a\n\n')
    const closed = 'a\n\n````md\n```\ncode\n```\n````\n\nout'
    expect(splitSettled(closed)).toEqual({
      settled: 'a\n\n````md\n```\ncode\n```\n````\n\n',
      tail: 'out'
    })
  })

  it('keeps a whole table in the tail until a blank line follows it', () => {
    const rows = '| a | b |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |'
    expect(splitSettled(`intro\n\n${rows}`)).toEqual({ settled: 'intro\n\n', tail: rows })
    expect(splitSettled(`intro\n\n${rows}\n\nafter`)).toEqual({
      settled: `intro\n\n${rows}\n\n`,
      tail: 'after'
    })
  })

  it('keeps a loose list together so items never render half tight, half loose', () => {
    const list = '- a\n\n- b\n\n- c'
    expect(splitSettled(`intro\n\n${list}`)).toEqual({ settled: 'intro\n\n', tail: list })
    expect(splitSettled(`intro\n\n${list}\n\nafter`).tail).toBe('after')
    const ordered = '1. a\n\n2. b'
    expect(splitSettled(`x\n\n${ordered}`).tail).toBe(ordered)
  })

  it('settles headings and tight lists at their blank line', () => {
    expect(splitSettled('## H\n\n- a\n- b\n\ntail')).toEqual({
      settled: '## H\n\n- a\n- b\n\n',
      tail: 'tail'
    })
  })

  it('settled + tail === content for every prefix of a realistic stream', () => {
    const full = buildBenchMarkdown()
    let acc = ''
    for (const token of splitIntoTokens(full, 400)) {
      acc += token
      const { settled, tail } = splitSettled(acc)
      expect(settled + tail).toBe(acc)
    }
  })
})

describe('stableTail', () => {
  it('passes prose and complete blocks through unchanged', () => {
    expect(stableTail('')).toBe('')
    expect(stableTail('just prose')).toBe('just prose')
    expect(stableTail('```c\nint a;\n```')).toBe('```c\nint a;\n```')
    expect(stableTail('- a\n- b')).toBe('- a\n- b')
  })

  it('holds back a table row while the table has no header separator yet', () => {
    expect(stableTail('| Signal | Addr')).toBe('')
    expect(stableTail('| Signal | Addr |\n')).toBe('')
    expect(stableTail('text\n| Signal | Addr |')).toBe('text')
    // The separator line itself is held until complete (a short one is not a table).
    expect(stableTail('| Signal | Addr |\n|---|-')).toBe('| Signal | Addr |')
  })

  it('lets partial rows through once the separator is in place', () => {
    const t = '| Signal | Addr |\n|---|---|\n| imu | 0x'
    expect(stableTail(t)).toBe(t)
  })

  it('holds back an unfinished fence opener so it never renders as stray backticks', () => {
    expect(stableTail('text\n``')).toBe('text')
    expect(stableTail('text\n`')).toBe('text')
    expect(stableTail('text\n~~')).toBe('text')
    expect(stableTail('``')).toBe('')
    // A complete opener with an info string is a real (unclosed) fence: keep it.
    expect(stableTail('text\n```python')).toBe('text\n```python')
  })
})
