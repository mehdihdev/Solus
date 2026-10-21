import { describe, expect, it } from 'vitest'
import type { PendingConfirmation } from '../../lib/api/solStream'
import { commandExitStatus, commandHeader, hasCommandOutput, isCommandTool } from './commandCard'

const row = (label: string, after: string | null): PendingConfirmation['preview'][number] => ({
  label,
  before: null,
  after
})

function card(tool: string, rows: PendingConfirmation['preview']): PendingConfirmation {
  return { confirmationId: 'c1', tool, summary: 's', preview: rows }
}

describe('isCommandTool', () => {
  it.each([
    'code.exec',
    'code.process_start',
    'code.run',
    'code.test',
    'code.install',
    'code.create_environment',
    'code.profile_capture',
    'code.process_input'
  ])('treats %s as a command card', (tool) => {
    expect(isCommandTool(tool)).toBe(true)
  })

  it.each(['onshape.set_variable', 'code.process_stop', 'code.profile_delete', 'code.plan'])(
    'does not treat %s as a command card',
    (tool) => {
      expect(isCommandTool(tool)).toBe(false)
    }
  )

  it('streams output only for exec, run and test', () => {
    expect(hasCommandOutput('code.exec')).toBe(true)
    expect(hasCommandOutput('code.run')).toBe(true)
    expect(hasCommandOutput('code.test')).toBe(true)
    expect(hasCommandOutput('code.process_start')).toBe(false)
    expect(hasCommandOutput('code.process_input')).toBe(false)
  })
})

describe('commandHeader for code.process_input (§11.2 card rows)', () => {
  it('names the process from its `process` row', () => {
    const header = commandHeader(
      card('code.process_input', [
        row('process', 'calibrate.sh'),
        row('prompt', 'Ready? [y/n]'),
        row('input', 'y')
      ])
    )
    expect(header).toEqual({ program: 'calibrate.sh', risks: [], sandboxed: false })
  })

  it('reads a path-like process row as its basename', () => {
    const header = commandHeader(card('code.process_input', [row('process', '/opt/bin/flash')]))
    expect(header?.program).toBe('flash')
  })
})

describe('commandHeader', () => {
  it('reads the program basename, risk badges and sandbox from the rows', () => {
    const header = commandHeader(
      card('code.exec', [
        row('program', '/opt/ros/jazzy/bin/colcon'),
        row('command', '["colcon","build"]'),
        row('sandbox', 'sandbox-exec — writes limited to the workspace, temp and tool caches'),
        row('risk', 'network, project_scripts')
      ])
    )
    expect(header).toEqual({
      program: 'colcon',
      risks: ['network', 'project_scripts'],
      sandboxed: true
    })
  })

  it('falls back to argv[0] of the command row for older tools', () => {
    const header = commandHeader(
      card('code.run', [row('command', '["/w/.venv/bin/python","main.py"]'), row('cwd', '.')])
    )
    expect(header).toEqual({ program: 'python', risks: [], sandboxed: false })
  })

  it('reads argv[0] from the first chunk of a chunked command', () => {
    const header = commandHeader(
      card('code.exec', [row('command 1/2', '["/usr/bin/ma\\"ke","-j8","targ'), row('cwd', '.')])
    )
    expect(header?.program).toBe('ma"ke')
  })

  it('shows no risk badges for "none flagged" and ignores malformed tokens', () => {
    expect(commandHeader(card('code.exec', [row('risk', 'none flagged')]))?.risks).toEqual([])
    expect(
      commandHeader(card('code.exec', [row('risk', 'network, <b>x</b>, install')]))?.risks
    ).toEqual(['network', 'install'])
  })

  it('reads the landlock sandbox kind as sandboxed', () => {
    expect(
      commandHeader(card('code.exec', [row('sandbox', 'landlock — writes limited')]))?.sandboxed
    ).toBe(true)
  })

  it('returns null for a non-command card', () => {
    expect(commandHeader(card('onshape.set_variable', [row('program', '/bin/x')]))).toBeNull()
  })

  it('has no program when neither row can be read', () => {
    expect(commandHeader(card('code.exec', [row('command', 'not json')]))?.program).toBeNull()
  })
})

describe('commandExitStatus', () => {
  it('reports the exit code of a command that ran and succeeded', () => {
    expect(commandExitStatus({ ok: true, value: { ok: true, exit_code: 0, reason: null } })).toBe(
      'exited 0'
    )
  })

  it('reports the exit code of a command that ran and failed (server shape ok:false)', () => {
    expect(commandExitStatus({ ok: true, value: { ok: false, exit_code: 2, reason: null } })).toBe(
      'exited 2'
    )
  })

  it('reports a timeout before the exit code', () => {
    expect(
      commandExitStatus({ ok: true, value: { ok: false, exit_code: -9, timed_out: true } })
    ).toBe('timed out')
  })

  it('reports a server refusal with its reason when nothing ran', () => {
    expect(
      commandExitStatus({
        ok: true,
        value: { ok: false, exit_code: null, reason: 'sandbox unavailable: x' }
      })
    ).toBe('refused: sandbox unavailable: x')
  })

  it('says not run for a refusal without a reason', () => {
    expect(commandExitStatus({ ok: true, value: { ok: false, exit_code: null } })).toBe(
      'refused: not run'
    )
  })

  it('caps a long refusal reason', () => {
    const status = commandExitStatus({ ok: true, value: { ok: false, reason: 'x'.repeat(500) } })
    expect(status).toBe(`refused: ${'x'.repeat(200)}`)
  })

  it('says finished when the outcome carries no exit code', () => {
    expect(commandExitStatus({ ok: true })).toBe('finished')
  })
})
