// SOLUSDEV-252 S2: pure helpers for the streaming-render benchmark
// (streamBench.test.tsx). Deterministic by construction — the reply text is
// identical on every run, so BEFORE/AFTER numbers compare like for like.

/** Token events per scripted reply. */
export const BENCH_TOKEN_COUNT = 2000

/** Structured citations carried by the closing `message` frame. */
export const BENCH_CITATIONS: readonly string[] = [
  'entity:imu_bno085',
  'entity:mcu_stm32g474',
  'file:firmware/src/i2c_bus.c'
]

const WORDS = (
  'the bus shares an address with the imu so the driver retries every read until the ' +
  'controller answers and the schematic pins pull-ups to both rails while firmware ' +
  'polls at ten hertz which the checker flags because the encoder also drives that ' +
  'line through a level shifter rated below the supply voltage on the carrier board'
).split(' ')

/** mulberry32 — a tiny seeded PRNG; enough to shuffle words deterministically. */
function mulberry32(seed: number): () => number {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

function paragraph(rand: () => number, words: number): string {
  const out: string[] = []
  for (let i = 0; i < words; i++) {
    const w = WORDS[Math.floor(rand() * WORDS.length)]
    // Sprinkle inline code the way SOL cites identifiers.
    out.push(i % 23 === 11 ? `\`${w}_${i}\`` : w)
  }
  return `${out.join(' ')}.`
}

function codeBlock(rand: () => number, lines: number): string {
  const body: string[] = []
  for (let i = 0; i < lines; i++) {
    const reg = Math.floor(rand() * 0xff)
    body.push(
      `  i2c_write(0x${reg.toString(16).padStart(2, '0')}, ${WORDS[i % WORDS.length]}_${i});`
    )
  }
  return ['```c', 'static int configure(void) {', ...body, '  return 0;', '}', '```'].join('\n')
}

function table(rows: number): string {
  const lines = ['| Signal | Address | Owner | Status |', '|---|---|---|---|']
  for (let i = 0; i < rows; i++) {
    lines.push(
      `| ${WORDS[(i * 7) % WORDS.length]}_${i} | 0x${(0x40 + i).toString(16)} | ${WORDS[(i * 3) % WORDS.length]} | ${i % 2 ? 'ok' : 'conflict'} |`
    )
  }
  return lines.join('\n')
}

/**
 * A realistic ~2,000-token (≈8k chars) markdown reply: headings, three
 * paragraphs, a 30-line fenced code block, a 6-row GFM table, a bullet list,
 * inline code. Same seed → same text, byte for byte.
 */
export function buildBenchMarkdown(seed = 252): string {
  const rand = mulberry32(seed)
  return [
    '# I2C address conflict on the sensor bus',
    '',
    paragraph(rand, 300),
    '',
    '## What the graph shows',
    '',
    paragraph(rand, 300),
    '',
    codeBlock(rand, 30),
    '',
    '## Affected signals',
    '',
    table(6),
    '',
    '## Suggested fix',
    '',
    ...Array.from(
      { length: 6 },
      (_, i) => `- ${paragraph(rand, 14).replace(/\.$/, '')} (step ${i + 1})`
    ),
    '',
    paragraph(rand, 300),
    ''
  ].join('\n')
}

/** Cut `text` into exactly `count` non-empty chunks (≈ BPE-sized when count ≈ len/4).
 *  Chunk boundaries ignore markdown syntax — exactly what a real token stream does. */
export function splitIntoTokens(text: string, count: number): string[] {
  const size = text.length / count
  const out: string[] = []
  for (let i = 0; i < count; i++) {
    out.push(text.slice(Math.round(i * size), Math.round((i + 1) * size)))
  }
  return out
}

/** One SSE frame as the backend emits it (`event:` + `data:` + blank line). */
export function encodeSseFrame(name: string, data: Record<string, unknown>): string {
  return `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`
}

export function median(values: readonly number[]): number {
  if (values.length === 0) return 0
  const sorted = [...values].sort((a, b) => a - b)
  const mid = sorted.length >> 1
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2
}
