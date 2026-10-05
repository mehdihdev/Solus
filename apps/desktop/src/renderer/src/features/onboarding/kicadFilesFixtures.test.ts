// SOLUSDEV-312 audit (criterion 3, client side): kicadFiles.ts is tested with
// synthetic one-liners elsewhere. This file feeds it the REAL committed KiCad
// files — the same bytes the API sniffer and the Cowork QA plan use — so the
// client classification and routing cannot drift from what the server accepts.
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import {
  assembleExportInputs,
  assembleKicadInputs,
  classifyKicadFile,
  PROJECT_UNSUPPORTED_ERROR,
  SCHEMATIC_UNSUPPORTED_ERROR,
  type EdaExportFile
} from './kicadFiles'

const HERE = dirname(fileURLToPath(import.meta.url))
const REPO = resolve(HERE, '../../../../../../..')
const SAMPLE = resolve(REPO, 'integrations/mcp/kicad/tests/fixtures/solus_sample')
const API_FIXTURES = resolve(REPO, 'packages/api/tests/fixtures')

const read = (path: string): string => readFileSync(path, 'utf8')
const file = (fileName: string, content: string): EdaExportFile => ({ fileName, content })

/** `NAME = """..."""` out of the Python sample module (the board has no committed file). */
function pythonConstant(name: string): string {
  const source = read(resolve(API_FIXTURES, 'kicad_sample.py'))
  const match = new RegExp(`^${name} = """([\\s\\S]*?)"""`, 'm').exec(source)
  if (!match) throw new Error(`${name} not found in kicad_sample.py`)
  return match[1]
}

const XML_NETLIST = read(resolve(SAMPLE, 'solus_sample.net.xml'))
const HOSTILE_NETLIST = read(resolve(SAMPLE, 'solus_sample_hostile.net.xml'))
const LARGE_NETLIST = read(resolve(SAMPLE, 'solus_sample_large.net.xml'))
const SCHEMATIC = read(resolve(SAMPLE, 'solus_sample.kicad_sch'))
const PROJECT = read(resolve(SAMPLE, 'solus_sample.kicad_pro'))
const SEXPR_NETLIST = read(resolve(API_FIXTURES, 'solus_sample.net'))
const BOARD = pythonConstant('KICAD_PCB')
const BOM = String.fromCharCode(0xfeff)

describe('classifyKicadFile on the committed KiCad files', () => {
  it.each([
    ['XML netlist', XML_NETLIST, 'xml-netlist'],
    ['hostile XML netlist', HOSTILE_NETLIST, 'xml-netlist'],
    ['1001-part XML netlist', LARGE_NETLIST, 'xml-netlist'],
    ['real kicad-cli S-expression netlist', SEXPR_NETLIST, 'sexpr-netlist'],
    ['board', BOARD, 'board'],
    ['schematic', SCHEMATIC, 'schematic'],
    ['project file', PROJECT, 'project']
  ] as const)('%s', (_label, content, kind) => {
    expect(classifyKicadFile(content)).toBe(kind)
  })

  it('still classifies by content after a UTF-8 BOM and leading blank lines', () => {
    expect(classifyKicadFile(`${BOM}\n\n${SEXPR_NETLIST}`)).toBe('sexpr-netlist')
    expect(classifyKicadFile(`${BOM}  ${XML_NETLIST}`)).toBe('xml-netlist')
  })
})

describe('assembleKicadInputs on the committed KiCad files', () => {
  it('routes each natural single pick to the right config key', () => {
    expect(assembleKicadInputs([file('a.xml', XML_NETLIST)])).toEqual({
      ok: true,
      inputs: { netlist: file('a.xml', XML_NETLIST) }
    })
    expect(assembleKicadInputs([file('a.net', SEXPR_NETLIST)])).toEqual({
      ok: true,
      inputs: { netlist: file('a.net', SEXPR_NETLIST) }
    })
    expect(assembleKicadInputs([file('a.kicad_pcb', BOARD)])).toEqual({
      ok: true,
      inputs: { board: file('a.kicad_pcb', BOARD) }
    })
  })

  it('routes a netlist plus board together in either pick order', () => {
    const net = file('a.net', SEXPR_NETLIST)
    const board = file('a.kicad_pcb', BOARD)
    const expected = { ok: true, inputs: { netlist: net, board } }
    expect(assembleKicadInputs([net, board])).toEqual(expected)
    expect(assembleKicadInputs([board, net])).toEqual(expected)
  })

  it('refuses the real schematic and project file with guidance, even beside a valid netlist', () => {
    expect(assembleKicadInputs([file('p.kicad_sch', SCHEMATIC)])).toEqual({
      ok: false,
      error: SCHEMATIC_UNSUPPORTED_ERROR
    })
    expect(assembleKicadInputs([file('p.kicad_pro', PROJECT)])).toEqual({
      ok: false,
      error: PROJECT_UNSUPPORTED_ERROR
    })
    expect(
      assembleKicadInputs([file('p.net', SEXPR_NETLIST), file('p.kicad_sch', SCHEMATIC)])
    ).toEqual({ ok: false, error: SCHEMATIC_UNSUPPORTED_ERROR })
  })

  it('refuses by CONTENT when a schematic or project is renamed to look like a netlist', () => {
    expect(assembleKicadInputs([file('fake.net', SCHEMATIC)])).toEqual({
      ok: false,
      error: SCHEMATIC_UNSUPPORTED_ERROR
    })
    expect(assembleKicadInputs([file('fake.xml', PROJECT)])).toEqual({
      ok: false,
      error: PROJECT_UNSUPPORTED_ERROR
    })
  })

  it('does not treat a netlist renamed .kicad_pcb as a board', () => {
    const result = assembleExportInputs('kicad', [file('x.kicad_pcb', SEXPR_NETLIST)])
    expect(result).toEqual({ ok: true, inputs: { netlist: file('x.kicad_pcb', SEXPR_NETLIST) } })
  })

  it('passes the hostile fixture through as an ordinary netlist (the server owns the safety)', () => {
    const result = assembleKicadInputs([file('hostile.xml', HOSTILE_NETLIST)])
    expect(result.ok).toBe(true)
  })
})
