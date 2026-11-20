// SOLUSDEV-329 Phase 4 — Python tools copy follows the SOL mode (ADR-016).
import { describe, expect, it } from 'vitest'
import {
  COPY,
  attentionBody,
  candidateReason,
  chooseErrorMessage,
  fixHint
} from './pythonToolsCopy'

describe('python_is_venv copy', () => {
  it('Guide explains a virtual environment and points at the Python it was made from', () => {
    expect(COPY.isVenv.Guide).toMatch(/virtual environment/i)
    expect(COPY.isVenv.Guide).toMatch(/made from/i)
    expect(chooseErrorMessage('python_is_venv', 'Guide')).toBe(COPY.isVenv.Guide)
  })

  it('Expert is terse', () => {
    expect(COPY.isVenv.Expert.length).toBeLessThan(COPY.isVenv.Guide.length)
    expect(chooseErrorMessage('python_is_venv', 'Expert')).toBe(COPY.isVenv.Expert)
  })

  it('a venv candidate and a venv fork error get their own text', () => {
    expect(candidateReason('python_is_venv', '3.12.7')).toMatch(/virtual environment/i)
    expect(fixHint('python_is_venv')).toMatch(/made from/i)
  })

  it('other choose errors keep their messages', () => {
    expect(chooseErrorMessage('python_not_cpython', 'Guide')).toBe(
      'That interpreter is not CPython, so the choice was not saved.'
    )
  })
})

describe('attentionBody', () => {
  it('Guide explains why the tools cannot run', () => {
    expect(attentionBody(['KiCad', 'Code'], 'Guide')).toBe(
      "KiCad, Code can't run until Solus sets up their Python environments on this computer."
    )
  })

  it('Expert names the tools and the state only', () => {
    expect(attentionBody(['KiCad', 'Code'], 'Expert')).toBe('KiCad, Code: setup needed.')
  })
})
