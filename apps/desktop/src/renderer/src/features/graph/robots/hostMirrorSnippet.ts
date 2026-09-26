/** Build explicit adapter text; this module never reads or writes the selected source. */
export interface MirrorOfferInput {
  file: string
  object: string
  anchor: string
  method: string
  mappings: string
  argument: string
  deviceId: string
  port: string
  capacity: string
}
export interface MirrorOffer {
  snippet: string
  prompt: string
}
const KEYWORDS = new Set(
  'False None True and as assert async await break class continue def del elif else except finally for from global if import in is lambda nonlocal not or pass raise return try while with yield'.split(
    ' '
  )
)
function identifier(value: string): boolean {
  return /^[A-Za-z][A-Za-z0-9_]*$/.test(value) && value.length <= 128 && !KEYWORDS.has(value)
}
function bounded(value: string, limit: number): boolean {
  return (
    value.length > 0 &&
    value.length <= limit &&
    ![...value].some((character) => character.charCodeAt(0) < 32 || character.charCodeAt(0) === 127)
  )
}
function integer(value: string, min: number, max: number): number {
  const parsed = Number(value)
  if (!/^\d+$/.test(value) || !Number.isSafeInteger(parsed) || parsed < min || parsed > max)
    throw new Error(`Enter a whole number from ${min} to ${max}.`)
  return parsed
}
const literal = (value: string): string => JSON.stringify(value)
function dictionary(entries: [string, string][]): string {
  return `{${entries.map(([key, value]) => `${literal(key)}: ${literal(value)}`).join(', ')}}`
}
export function prepareMirrorOffer(
  input: MirrorOfferInput,
  sourceId: string,
  robotId: string
): MirrorOffer {
  validateMirrorTarget(input)
  const port = integer(input.port, 1, 65535)
  const capacity = integer(input.capacity, 1, 1024)
  const { signals, units } = parseMirrorMappings(input.mappings)
  const argument = mirrorArgument(input.argument)
  const snippet = `import solus_telemetry as solus\nsolus_mirror = solus.mirror(${input.object}, config=solus.MirrorConfig(device_id=${literal(input.deviceId)}, port=${port}, methods=(solus.MethodAdapter(method=${literal(input.method)}, signals=${dictionary(signals)}, argument=${argument}),), units=${dictionary(units)}, capacity=${capacity}))`
  const prompt = `Request a complete file diff review for the explicitly accepted local host source ${literal(sourceId)}, robot ${literal(robotId)}. Selected relative Python file: ${literal(input.file)}. This is a review request, not approval to write or run code.
Use machine.read_file to verify this existing file in the authorized machine workspace corresponding to that accepted local source. Do not create a missing file, switch folders, infer a remote repository, or broaden file grants. If the source and machine workspace cannot be matched, stop and explain the missing authorization.
Read the complete file. Find exactly one line whose text is ${literal(input.anchor)}. Require this location to be after setup of ${literal(input.object)} and before its repeating control loop. If the anchor is absent, ambiguous, inside a repeating loop, or the object/method is not supported by the explicit adapter, stop and ask for corrected choices. Do not execute the file or call the control object to test it.
Insert exactly the following two lines immediately after that anchor, using its indentation. Preserve every existing byte otherwise. Refuse if solus or solus_mirror already binds another value or an existing mirror is installed. Do not invent any adapter, telemetry mapping, teardown logic or control commands.
${snippet}
Request machine.write_file with that complete resulting content and create_dirs=false so its central fingerprinted before/after confirmation card displays the actual diff. Wait for my explicit confirmation on that card. Never claim installation from a preview. No shell commands, dependency installation, loop start, device access, or hardware writes are authorized by this request.`
  if (prompt.length > 8000)
    throw new Error(
      'The complete review exceeds 8000 characters. Reduce the signal mappings or shorten their names before previewing again.'
    )
  return { snippet, prompt }
}

function validateMirrorTarget(input: MirrorOfferInput): void {
  validateMirrorFile(input.file)
  if (
    !identifier(input.object) ||
    !identifier(input.method) ||
    ['solus', 'solus_mirror'].includes(input.object)
  )
    throw new Error('Choose a Python control-object variable and one public synchronous method.')
  if (!bounded(input.anchor, 400) || !input.anchor.trim())
    throw new Error(
      'Provide one exact existing line after object setup and before the repeating loop.'
    )
  if (!bounded(input.deviceId, 512)) throw new Error('Provide an explicit device ID.')
}

function validateMirrorFile(file: string): void {
  if (
    !bounded(file, 400) ||
    file.includes('\\') ||
    file.includes(':') ||
    file.startsWith('/') ||
    !file.endsWith('.py') ||
    file.split('/').some((part) => !part || part === '.' || part === '..' || part.startsWith('.'))
  )
    throw new Error('Choose an existing Python file relative to the accepted local folder.')
}

function parseMirrorMappings(mappings: string): {
  signals: [string, string][]
  units: [string, string][]
} {
  const rows = mappings.split('\n').filter((row) => row.trim())
  if (!rows.length || rows.length > 256) throw new Error('Provide 1–256 signal mappings.')
  const signals: [string, string][] = [],
    units: [string, string][] = []
  const seen = new Set<string>()
  for (const row of rows) {
    const [signal, assignment, extra] = row.split('=')
    const [key, unit, more] = (assignment ?? '').split('|')
    validateMirrorMapping(signal, key, unit, extra, more, seen)
    seen.add(signal)
    signals.push([signal, key])
    if (unit !== undefined) units.push([signal, unit])
  }
  return { signals, units }
}

function mirrorArgument(value: string): string {
  let argument = 'None'
  if (value !== '') {
    argument = /^\d+$/.test(value) ? String(integer(value, 0, 64)) : literal(value)
    if (!/^\d+$/.test(value) && !identifier(value))
      throw new Error('Choose a zero-based argument position or a keyword argument name.')
  }
  return argument
}

function validateMirrorMapping(
  signal: string,
  key: string,
  unit: string | undefined,
  extra: string | undefined,
  more: string | undefined,
  seen: Set<string>
): void {
  if (
    extra !== undefined ||
    more !== undefined ||
    !bounded(signal, 128) ||
    !bounded(key, 128) ||
    (unit !== undefined && !bounded(unit, 32)) ||
    seen.has(signal)
  )
    throw new Error(
      'Use unique signal=dictionary_key|unit mappings, one per line; unit is optional.'
    )
}
