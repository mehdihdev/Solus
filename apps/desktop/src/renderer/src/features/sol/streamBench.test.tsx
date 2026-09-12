// SOLUSDEV-252 S2: the streaming-render benchmark. Mounts the REAL <SolChat/>
// (real solChatStore.sendMessage → applyEvent → patch → zustand → React tree →
// SolMarkdown → react-markdown) and drives it with a scripted 2,000-token SSE
// reply through the REAL createSolStreamParser. Only the network is stubbed:
// `streamSolMessage` is mocked to feed frames into the parser and deliver the
// parsed events to sendMessage's onEvent exactly as the transport does.
//
// The orchestrator re-runs this file UNCHANGED before and after the S2
// optimisation lanes; the console.info table below is the report. The
// assertions are deliberately loose upper bounds that must hold in both
// states — they pin "not catastrophically worse", not a target.
//
// jsdom measures RENDER WORK (reconcile + markdown parse + DOM mutation), not
// paint or frame time — there is no layout or compositor here.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { Profiler } from 'react'
import ReactMarkdown from 'react-markdown'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import * as solApi from './solApi'
import type * as resources from '../../lib/api/resources'
import { useSolSessionStore } from './solSessionStore'
import { resetSolChatSessions, useSolChatStore } from './solChatStore'
import { createSolStreamParser } from './solStream'
import { SolChat } from './SolChat'
import {
  BENCH_CITATIONS,
  BENCH_TOKEN_COUNT,
  buildBenchMarkdown,
  encodeSseFrame,
  median,
  splitIntoTokens
} from './streamBench'

// ---- probes ----------------------------------------------------------------
// Render counting without exports from SolChat: every JSX element the app code
// creates passes through the (dev) jsx runtime. A MessageRow render creates
// exactly one `div.sol-msg-in`; a SolMarkdown render (= one markdown re-parse,
// react-markdown parses synchronously in render) creates exactly one
// <ReactMarkdown> element. Externalised node_modules bypass this mock, so
// react-markdown's own internals are not counted.
const probe = { rows: 0, parses: 0 }
type JsxFn = (type: unknown, props: Record<string, unknown> | null, ...rest: unknown[]) => unknown
function counting(fn: JsxFn): JsxFn {
  return (type, props, ...rest) => {
    if (type === 'div' && props?.className === 'sol-msg-in') probe.rows++
    else if (type === ReactMarkdown) probe.parses++
    return fn(type, props, ...rest)
  }
}
vi.mock('react/jsx-dev-runtime', async (importOriginal) => {
  const mod = await importOriginal<{ jsxDEV: JsxFn }>()
  return { ...mod, jsxDEV: counting(mod.jsxDEV) }
})
vi.mock('react/jsx-runtime', async (importOriginal) => {
  const mod = await importOriginal<{ jsx: JsxFn; jsxs: JsxFn }>()
  return { ...mod, jsx: counting(mod.jsx), jsxs: counting(mod.jsxs) }
})

vi.mock('./solApi', () => ({
  createSolConversation: vi.fn(),
  listSolTurns: vi.fn(),
  streamSolMessage: vi.fn()
}))
vi.mock('../../lib/api/resources', async (importOriginal) => ({
  ...(await importOriginal<typeof resources>()),
  classifyQuery: vi.fn().mockReturnValue(new Promise(() => undefined)),
  decideSolConfirmation: vi.fn(),
  listEntities: vi.fn()
}))
const createSolConversation = vi.mocked(solApi.createSolConversation)
const listSolTurns = vi.mocked(solApi.listSolTurns)
const streamSolMessage = vi.mocked(solApi.streamSolMessage)

// ---- scripted stream -------------------------------------------------------
const MARKDOWN = buildBenchMarkdown()
const TOKENS = splitIntoTokens(MARKDOWN, BENCH_TOKEN_COUNT)
const TOKEN_FRAMES = TOKENS.map((text) => encodeSseFrame('token', { text }))
const TAIL_FRAMES =
  encodeSseFrame('message', {
    role: 'assistant',
    content: MARKDOWN,
    citations: BENCH_CITATIONS
  }) + encodeSseFrame('done', { conversation_id: 'c1', turn_id: 't1' })

type Mode = 'sync' | 'paced'

const macrotask = (): Promise<void> =>
  new Promise((resolve) => {
    if (typeof setImmediate === 'function') setImmediate(resolve)
    else setTimeout(resolve, 0)
  })

/** Let React drain: sync-lane store updates flush in a microtask, the scheduler
 *  in a macrotask; two macrotasks + one animation frame covers both. */
async function flushRender(): Promise<void> {
  await macrotask()
  await macrotask()
  await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()))
}

interface RunMetrics {
  ms: number
  commits: number
  rows: number
  storeNotifies: number
  parses: number
}

async function benchRun(mode: Mode): Promise<RunMetrics> {
  resetSolChatSessions()
  useSolSessionStore.setState({ conversationByProject: {} })
  const parser = createSolStreamParser()
  let ms = 0
  streamSolMessage.mockImplementation(async ({ onEvent }) => {
    const t0 = performance.now()
    if (mode === 'sync') {
      // One chunk carrying every frame: the transport parses it and delivers
      // all events synchronously from one microtask.
      for (const event of parser.push(TOKEN_FRAMES.join(''))) onEvent(event)
    } else {
      // One chunk per token, a macrotask between — network pacing.
      for (const frame of TOKEN_FRAMES) {
        for (const event of parser.push(frame)) onEvent(event)
        await macrotask()
      }
    }
    await flushRender()
    ms = performance.now() - t0
    for (const event of parser.push(TAIL_FRAMES)) onEvent(event)
  })

  let commits = 0
  const view = render(
    <Profiler id="sol-chat" onRender={() => commits++}>
      <SolChat projectId="p1" />
    </Profiler>
  )
  await flushRender()
  // Baseline after mount: only the streaming turn is measured.
  commits = 0
  probe.rows = 0
  probe.parses = 0
  let storeNotifies = 0
  const unsubscribe = useSolChatStore.subscribe(() => storeNotifies++)
  try {
    fireEvent.change(screen.getByPlaceholderText('Ask about a signal, a change, a part…'), {
      target: { value: 'bench' }
    })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))
    await waitFor(() => expect(screen.getByTestId('citations-region')).toBeInTheDocument(), {
      timeout: 120_000
    })
    await flushRender()
  } finally {
    unsubscribe()
    view.unmount()
  }
  return { ms, commits, rows: probe.rows, storeNotifies, parses: probe.parses }
}

const RUNS = 3

function summarise(runs: RunMetrics[]): RunMetrics {
  const pick = (k: keyof RunMetrics): number => median(runs.map((r) => r[k]))
  return {
    ms: Math.round(pick('ms')),
    commits: pick('commits'),
    rows: pick('rows'),
    storeNotifies: pick('storeNotifies'),
    parses: pick('parses')
  }
}

// ---- tests -----------------------------------------------------------------
describe('streamBench helpers', () => {
  it('builds a deterministic ~2k-token markdown reply with every construct', () => {
    expect(buildBenchMarkdown()).toBe(MARKDOWN)
    expect(MARKDOWN.length).toBeGreaterThan(7000)
    expect(MARKDOWN.length).toBeLessThan(10_000)
    expect(MARKDOWN).toMatch(/^# /m)
    expect(MARKDOWN).toMatch(/^## /m)
    expect(MARKDOWN.match(/```/g)).toHaveLength(2)
    expect(MARKDOWN.match(/^\|.*\|$/gm)?.length).toBe(8) // header + rule + 6 rows
    expect(MARKDOWN.match(/^- /gm)?.length).toBeGreaterThanOrEqual(5)
    expect(MARKDOWN).toMatch(/`\w+`/)
  })

  it('splits into exactly N tokens that re-join to the source', () => {
    expect(TOKENS).toHaveLength(BENCH_TOKEN_COUNT)
    expect(TOKENS.join('')).toBe(MARKDOWN)
    expect(TOKENS.every((t) => t.length > 0)).toBe(true)
  })

  it('encodes an SSE frame the parser accepts', () => {
    const events = createSolStreamParser().push(encodeSseFrame('token', { text: 'hi' }))
    expect(events).toEqual([{ type: 'token', text: 'hi' }])
  })

  it('median of odd and even lists', () => {
    expect(median([3, 1, 2])).toBe(2)
    expect(median([4, 1, 3, 2])).toBe(2.5)
  })
})

describe('SOL streaming render benchmark (jsdom: render work, not paint)', () => {
  let actEnvironment: unknown
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    createSolConversation.mockResolvedValue({ id: 'c1' } as solApi.SolConversation)
    listSolTurns.mockResolvedValue([])
    // Updates arrive from the store outside act — as in the app. Silence the
    // act warning for the bench; RTL restores whatever it finds afterwards.
    const g = globalThis as { IS_REACT_ACT_ENVIRONMENT?: unknown }
    actEnvironment = g.IS_REACT_ACT_ENVIRONMENT
    g.IS_REACT_ACT_ENVIRONMENT = false
  })
  afterEach(() => {
    ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: unknown }).IS_REACT_ACT_ENVIRONMENT =
      actEnvironment
  })

  it('streams 2,000 tokens through the real store and tree in both delivery modes', async () => {
    const results: Record<Mode, RunMetrics> = { sync: summarise([]), paced: summarise([]) }
    for (const mode of ['sync', 'paced'] as const) {
      const runs: RunMetrics[] = []
      for (let i = 0; i < RUNS; i++) runs.push(await benchRun(mode))
      results[mode] = summarise(runs)
    }
    const row = (m: RunMetrics): string =>
      `${String(m.ms).padStart(7)} ms | ${String(m.commits).padStart(7)} | ${String(m.rows).padStart(7)} | ${String(m.storeNotifies).padStart(7)} | ${String(m.parses).padStart(7)}`
    console.info(
      [
        `SOL stream bench — ${BENCH_TOKEN_COUNT} tokens, ${MARKDOWN.length} chars, median of ${RUNS} runs (jsdom: render work, not paint)`,
        'mode  |  tokens ms | commits | MsgRow  | notify  | mdparse',
        `sync  | ${row(results.sync)}`,
        `paced | ${row(results.paced)}`
      ].join('\n')
    )
    // Loose ceilings that hold before AND after the optimisation lanes.
    for (const m of Object.values(results)) {
      expect(m.commits).toBeLessThanOrEqual(2500)
      expect(m.parses).toBeLessThanOrEqual(2500)
      expect(m.storeNotifies).toBeLessThanOrEqual(2500)
      expect(m.rows).toBeLessThanOrEqual(6000)
      expect(m.ms).toBeLessThan(120_000)
    }
    // The transcript settled with the full reply and its citations.
    expect(screen.queryByTestId('citations-region')).not.toBeInTheDocument() // unmounted
  }, 600_000)
})
