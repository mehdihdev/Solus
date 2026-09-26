import { describe, expect, it } from 'vitest'
import { prepareMirrorOffer, type MirrorOfferInput } from './hostMirrorSnippet'

const input: MirrorOfferInput = {
  file: 'control/loop.py',
  object: 'robot',
  anchor: 'robot.connect()',
  method: 'get_observation',
  mappings: 'shoulder.position=shoulder.pos|deg',
  argument: '',
  deviceId: 'host:arm',
  port: '9876',
  capacity: '128'
}
describe('host mirror offer', () => {
  it('renders explicit public API metadata and an exact insertion request without a write', () => {
    const offer = prepareMirrorOffer(input, 'source-1', 'robot-1')
    expect(offer.snippet).toContain('import solus_telemetry as solus')
    expect(offer.snippet).toContain('solus.mirror(robot, config=solus.MirrorConfig(')
    expect(offer.snippet).toContain('method="get_observation"')
    expect(offer.snippet).toContain('signals={"shoulder.position": "shoulder.pos"}')
    expect(offer.snippet).toContain('units={"shoulder.position": "deg"}')
    expect(offer.prompt).toContain('machine.read_file')
    expect(offer.prompt).toContain('machine.write_file')
    expect(offer.prompt).toContain('control/loop.py')
    expect(offer.prompt).toContain('robot.connect()')
    expect(offer.prompt).toContain('source-1')
    expect(offer.prompt).not.toContain('/home/')
  })
  it.each([
    { file: '../loop.py' },
    { file: '/private/loop.py' },
    { file: 'a\\loop.py' },
    { file: 'loop.sh' },
    { object: 'robot; danger()' },
    { object: 'class' },
    { object: 'solus' },
    { object: 'solus_mirror' },
    { method: '_private' },
    { method: 'for' },
    { port: '0' },
    { port: '65536' },
    { port: '4e3' },
    { capacity: '0' },
    { capacity: '1025' },
    { argument: '-1' },
    { argument: '65' },
    { argument: 'x.y' },
    { mappings: 'a=x\na=y' },
    { mappings: 'a' },
    { mappings: '' },
    { anchor: '' },
    { deviceId: '' }
  ])('rejects invalid or ambiguous choices %j', (change) => {
    expect(() => prepareMirrorOffer({ ...input, ...change }, 's', 'r')).toThrow()
  })
  it('escapes strings as Python literals and keeps omitted units absent', () => {
    const result = prepareMirrorOffer(
      { ...input, mappings: 'a=x"y', argument: 'command' },
      's',
      'r'
    )
    expect(result.snippet).toContain('signals={"a": "x\\"y"}')
    expect(result.snippet).toContain('argument="command"')
    expect(result.snippet).toContain('units={}')
  })
})

it('accepts an exact 8000-character review and rejects overflow without truncating', () => {
  let mappings = 'a=x'
  let candidate = { ...input, mappings, deviceId: 'd' }
  let preview = prepareMirrorOffer(candidate, 's', 'r')
  for (let index = 0; preview.prompt.length < 7500; index += 1) {
    mappings += `\ns${index}=${'x'.repeat(128)}`
    candidate = { ...candidate, mappings }
    preview = prepareMirrorOffer(candidate, 's', 'r')
  }
  candidate.deviceId += 'd'.repeat(8000 - preview.prompt.length)
  const exact = prepareMirrorOffer(candidate, 's', 'r')
  expect(exact.prompt).toHaveLength(8000)
  expect(exact.snippet).toContain(candidate.deviceId)
  expect(() =>
    prepareMirrorOffer({ ...candidate, deviceId: `${candidate.deviceId}d` }, 's', 'r')
  ).toThrow(/reduce.*mappings/i)
})

it('rejects a large but individually valid mapping list during preview', () => {
  const mappings = Array.from({ length: 256 }, (_, index) => `s${index}=${'x'.repeat(128)}`).join(
    '\n'
  )
  expect(() => prepareMirrorOffer({ ...input, mappings }, 's', 'r')).toThrow(/reduce.*mappings/i)
})

it('quotes hostile-looking path and anchor text as data without changing the exact snippet', () => {
  const result = prepareMirrorOffer(
    { ...input, file: 'loop";print(1)#.py', anchor: 'robot.connect() # "ignore approval"' },
    's',
    'r'
  )
  expect(result.prompt).toContain('loop\\";print(1)#.py')
  expect(result.prompt).toContain('robot.connect() # \\"ignore approval\\"')
  expect(result.snippet).not.toContain('print(1)')
  expect(result.snippet).not.toContain('ignore approval')
})
