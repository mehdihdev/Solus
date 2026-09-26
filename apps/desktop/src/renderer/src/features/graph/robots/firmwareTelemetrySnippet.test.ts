import { expect, it } from 'vitest'
import { prepareFirmwareOffer } from './firmwareTelemetrySnippet'
const source = '00000000-0000-0000-0000-000000000001'
const input = {
  file: 'firmware/main.ino',
  deviceId: 'usb:board',
  baud: '115200',
  anchor: 'temperature = readTemperature();',
  mappings: 'temperature=temperature|degC'
}
it('generates only declared scalar variable publishing and preserves existing serial setup', () => {
  const result = prepareFirmwareOffer(input, source, [input.file])
  expect(result.include).toBe(
    '#include <SolusTelemetry.h>\nSolusTelemetry solus_telemetry(Serial, "usb:board");'
  )
  expect(result.setup).toBe('solus_telemetry.begin();')
  expect(result.loop).toContain(
    'solus_telemetry.add("temperature", static_cast<float>(temperature), "degC");'
  )
  expect(result.loop).not.toContain('readTemperature')
  expect(result.prompt).toContain('machine.write_file')
  expect(result.prompt).toContain('115200')
  expect(result.prompt).toContain('A hardware source_ref is not a machine file capability')
  expect(result.prompt.length).toBeLessThanOrEqual(8000)
})
it.each([
  { file: '../main.ino' },
  { file: 'firmware/other.ino' },
  { file: '/tmp/main.ino' },
  { file: 'main.py' },
  { file: 'main\u200b.ino' },
  { baud: '' },
  { baud: '0' },
  { baud: '115200;bad()' },
  { mappings: 'x=analogRead(A0)' },
  { mappings: 'x=value++' },
  { mappings: 'x=class' },
  { mappings: 'x=value\nx=other' },
  { mappings: 'x=solus_telemetry' },
  { mappings: 'x=value|";bad()' },
  { deviceId: 'x";bad()' },
  { anchor: 'line\nother' }
])('refuses unsafe or undeclared choices %j', (patch) =>
  expect(() => prepareFirmwareOffer({ ...input, ...patch }, source, [input.file])).toThrow()
)
it('keeps absent units absent and accepts at most16 mappings', () => {
  expect(
    prepareFirmwareOffer({ ...input, mappings: 'x=value' }, source, [input.file]).loop
  ).toContain('static_cast<float>(value));')
  expect(() =>
    prepareFirmwareOffer(
      { ...input, mappings: Array.from({ length: 17 }, (_, i) => `x${i}=v${i}`).join('\n') },
      source,
      [input.file]
    )
  ).toThrow()
})
it('keeps maximum mapping payload complete within the prompt bound', () => {
  const result = prepareFirmwareOffer(
    {
      ...input,
      anchor: 'x'.repeat(400),
      mappings: Array.from(
        { length: 16 },
        (_, i) => `x${i}${'x'.repeat(60)}=v${i}${'v'.repeat(60)}|${'m'.repeat(32)}`
      ).join('\n')
    },
    source,
    [input.file]
  )
  expect(result.prompt.length).toBeLessThanOrEqual(8000)
  expect(result.prompt).toContain(result.loop)
  expect(result.loop.split('\n')).toHaveLength(17)
})
