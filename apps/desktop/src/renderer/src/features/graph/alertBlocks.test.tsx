import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { SevBadge, CodeBlock, DiffBlock, BeforeAfter } from './alertBlocks'
import { ALERTS } from '../workspace/workspaceData.constants'
import type { DiffLine } from '../workspace/workspaceData.constants'

const a1 = ALERTS[0]

describe('SevBadge', () => {
  it('shows the uppercase severity while the alert is open', () => {
    render(<SevBadge sev="critical" state="open" />)
    expect(screen.getByText('CRITICAL')).toBeInTheDocument()
  })

  it('shows RESOLVED once resolved, regardless of severity', () => {
    render(<SevBadge sev="warning" state="resolved" />)
    expect(screen.getByText('RESOLVED')).toBeInTheDocument()
    expect(screen.queryByText('WARNING')).toBeNull()
  })
})

describe('CodeBlock', () => {
  it('renders every code line', () => {
    render(<CodeBlock lines={['line one', 'line two']} />)
    expect(screen.getByText('line one')).toBeInTheDocument()
    expect(screen.getByText('line two')).toBeInTheDocument()
  })

  it('highlights hot lines with the warn accent border', () => {
    render(<CodeBlock lines={['cold', 'hot']} hot={[1]} />)
    // jest-dom's toHaveStyle drops var() shorthands; assert the inline style directly.
    expect(screen.getByText('hot').style.borderLeft).toBe('2px solid var(--warn)')
    expect(screen.getByText('cold').style.borderLeft).toBe('2px solid transparent')
  })
})

describe('DiffBlock', () => {
  const lines: readonly DiffLine[] = [
    { t: 'del', s: 'old line' },
    { t: 'add', s: 'new line' },
    { t: 'ctx', s: 'context line' }
  ]

  it('prefixes deletions with − and additions with +', () => {
    render(<DiffBlock lines={lines} />)
    expect(screen.getByText('old line').textContent).toBe('−old line')
    expect(screen.getByText('new line').textContent).toBe('+new line')
    expect(screen.getByText('context line').textContent).toBe(' context line')
  })
})

describe('BeforeAfter', () => {
  it('renders the before/after revision columns with their rows', () => {
    render(<BeforeAfter change={a1.change} />)
    expect(screen.getByText('BEFORE · REV 41')).toBeInTheDocument()
    expect(screen.getByText('AFTER · REV 42')).toBeInTheDocument()
    expect(screen.getByText('DRV8833')).toBeInTheDocument()
    expect(screen.getByText('DRV8316C')).toBeInTheDocument()
  })
})
