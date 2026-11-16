// SOLUSDEV-327 — the sidebar's per-screen tag, greeting, chips and placeholder (sol-sidebar.md §6).
import { describe, expect, it } from 'vitest'
import { MAX_TAG_NAME, sidebarCopy } from './sidebarCopy'

describe('sidebarCopy', () => {
  it('names the workspace and its focused node', () => {
    const copy = sidebarCopy('workspace', 'imu')
    expect(copy.tag).toBe('WORKSPACE · imu')
    expect(copy.placeholder).toBe('Ask SOL about anything in the workspace')
    expect(copy.suggestions.length).toBeGreaterThan(0)
  })

  it('shows only the screen when nothing is focused', () => {
    expect(sidebarCopy('workspace', null).tag).toBe('WORKSPACE')
  })

  it('ignores focus outside the workspace', () => {
    expect(sidebarCopy('bench', 'imu').tag).toBe('LIVE BENCH')
    expect(sidebarCopy('bench', null).placeholder).toBe('Ask SOL about anything on the bench')
  })

  it('caps a long focused name', () => {
    const tag = sidebarCopy('workspace', 'x'.repeat(80)).tag
    expect(tag).toBe(`WORKSPACE · ${'x'.repeat(MAX_TAG_NAME - 1)}…`)
  })

  it('collapses whitespace and control characters in the name', () => {
    expect(sidebarCopy('workspace', ' imu\n\tdriver ').tag).toBe('WORKSPACE · imu driver')
    expect(sidebarCopy('workspace', '   ').tag).toBe('WORKSPACE')
  })

  it('strips bidi overrides and invisible format characters', () => {
    expect(sidebarCopy('workspace', 'imu\u202Egpj.exe\u200B').tag).toBe('WORKSPACE · imugpj.exe')
    expect(sidebarCopy('workspace', '\u2066\u200F').tag).toBe('WORKSPACE')
  })

  it('caps by code point, never splitting a surrogate pair', () => {
    const tag = sidebarCopy('workspace', '🤖'.repeat(40)).tag
    expect(tag).toBe(`WORKSPACE · ${'🤖'.repeat(MAX_TAG_NAME - 1)}…`)
  })

  it('gives screens without their own copy a plain greeting and no chips', () => {
    const copy = sidebarCopy('billing', null)
    expect(copy.tag).toBe('BILLING')
    expect(copy.greeting).toBe('Ask SOL about this project.')
    expect(copy.suggestions).toEqual([])
    expect(copy.placeholder).toBe('Ask SOL about this project')
  })

  it('labels detail routes', () => {
    expect(sidebarCopy('alert', null).tag).toBe('ALERT')
    expect(sidebarCopy('ext-page', null).tag).toBe('EXTENSION')
  })
})
