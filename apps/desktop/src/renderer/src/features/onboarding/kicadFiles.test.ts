// Pure KiCad file handling for the connect wizard's file step (SOLUSDEV-252):
// content sniffing (extensions are never trusted), routing each picked file
// to its config key, and the instant guidance a schematic / project pick gets
// on the client instead of after a failed sync.
import { describe, it, expect } from 'vitest'
import {
  allowsMultipleFiles,
  assembleExportInputs,
  assembleKicadInputs,
  classifyKicadFile,
  exportFileAccept,
  exportFilePrompt,
  MULTIPLE_BOARDS_ERROR,
  MULTIPLE_NETLISTS_ERROR,
  NO_FILES_ERROR,
  PROJECT_UNSUPPORTED_ERROR,
  SCHEMATIC_UNSUPPORTED_ERROR,
  UNRECOGNIZED_FILE_ERROR,
  type EdaExportFile
} from './kicadFiles'

const XML = { fileName: 'power.xml', content: '<?xml version="1.0"?><export version="E"/>' }
const SEXPR = { fileName: 'power.net', content: '(export (version "E") (design))' }
const BOARD = { fileName: 'power.kicad_pcb', content: '(kicad_pcb (version 20240108))' }
const SCH = { fileName: 'power.kicad_sch', content: '(kicad_sch (version 20231120))' }
const PRO = {
  fileName: 'power.kicad_pro',
  content: '{\n  "board": {},\n  "meta": { "filename": "p" }\n}'
}
const JUNK = { fileName: 'notes.net', content: 'hello world' }

describe('classifyKicadFile', () => {
  it('recognises an XML netlist by its leading tag', () => {
    expect(classifyKicadFile(XML.content)).toBe('xml-netlist')
  })

  it('recognises the S-expression netlist export', () => {
    expect(classifyKicadFile(SEXPR.content)).toBe('sexpr-netlist')
  })

  it('recognises a board file', () => {
    expect(classifyKicadFile(BOARD.content)).toBe('board')
  })

  it('recognises a schematic', () => {
    expect(classifyKicadFile(SCH.content)).toBe('schematic')
  })

  it('recognises a project file by its JSON keys within the first 4 KiB', () => {
    expect(classifyKicadFile(PRO.content)).toBe('project')
    expect(classifyKicadFile('{"kicad_pro": 1}')).toBe('project')
  })

  it('does not call arbitrary JSON a project', () => {
    expect(classifyKicadFile('{"foo": "bar"}')).toBe('unknown')
  })

  it('does not scan past 4 KiB for the project marker', () => {
    const late = `{"pad": "${'x'.repeat(5000)}", "meta": {}}`
    expect(classifyKicadFile(late)).toBe('unknown')
  })

  it('ignores a BOM and leading whitespace before sniffing', () => {
    expect(classifyKicadFile('\uFEFF\n  <export/>')).toBe('xml-netlist')
    expect(classifyKicadFile('\uFEFF(kicad_pcb)')).toBe('board')
    expect(classifyKicadFile('\r\n\t(export)')).toBe('sexpr-netlist')
    expect(classifyKicadFile('   \n(kicad_sch)')).toBe('schematic')
  })

  it('is content-driven: the extension is never consulted', () => {
    // A .net that is really a board and an .xml that is really a schematic.
    expect(classifyKicadFile(BOARD.content)).toBe('board')
    expect(classifyKicadFile(SCH.content)).toBe('schematic')
  })

  it('returns unknown for anything else, including empty content', () => {
    expect(classifyKicadFile(JUNK.content)).toBe('unknown')
    expect(classifyKicadFile('')).toBe('unknown')
    expect(classifyKicadFile('(footprint "x")')).toBe('unknown')
  })
})

describe('assembleKicadInputs', () => {
  it('routes a lone XML netlist to `netlist`', () => {
    expect(assembleKicadInputs([XML])).toEqual({ ok: true, inputs: { netlist: XML } })
  })

  it('routes a lone S-expression netlist to `netlist`', () => {
    expect(assembleKicadInputs([SEXPR])).toEqual({ ok: true, inputs: { netlist: SEXPR } })
  })

  it('routes a lone board to `board` with no netlist key at all', () => {
    const result = assembleKicadInputs([BOARD])
    expect(result).toEqual({ ok: true, inputs: { board: BOARD } })
    if (result.ok) expect('netlist' in result.inputs).toBe(false)
  })

  it('routes a netlist plus a board regardless of pick order', () => {
    expect(assembleKicadInputs([BOARD, SEXPR])).toEqual({
      ok: true,
      inputs: { netlist: SEXPR, board: BOARD }
    })
  })

  it('routes by CONTENT even when the extension lies', () => {
    const misnamedBoard: EdaExportFile = { fileName: 'export.net', content: BOARD.content }
    expect(assembleKicadInputs([misnamedBoard])).toEqual({
      ok: true,
      inputs: { board: misnamedBoard }
    })
  })

  it('refuses a schematic with export guidance', () => {
    expect(assembleKicadInputs([SCH])).toEqual({ ok: false, error: SCHEMATIC_UNSUPPORTED_ERROR })
  })

  it('refuses a project file with guidance', () => {
    expect(assembleKicadInputs([PRO])).toEqual({ ok: false, error: PROJECT_UNSUPPORTED_ERROR })
  })

  it('refuses two netlists (of any format mix)', () => {
    expect(assembleKicadInputs([XML, SEXPR])).toEqual({ ok: false, error: MULTIPLE_NETLISTS_ERROR })
    expect(assembleKicadInputs([XML, { ...XML, fileName: 'b.xml' }])).toEqual({
      ok: false,
      error: MULTIPLE_NETLISTS_ERROR
    })
  })

  it('refuses two boards', () => {
    expect(assembleKicadInputs([BOARD, { ...BOARD, fileName: 'b.kicad_pcb' }])).toEqual({
      ok: false,
      error: MULTIPLE_BOARDS_ERROR
    })
  })

  it('refuses an unrecognised file even alongside a valid one', () => {
    expect(assembleKicadInputs([XML, JUNK])).toEqual({ ok: false, error: UNRECOGNIZED_FILE_ERROR })
  })

  it('refuses an empty pick', () => {
    expect(assembleKicadInputs([])).toEqual({ ok: false, error: NO_FILES_ERROR })
  })

  it('reports in priority order: schematic > project > netlists > boards > unknown', () => {
    const everything = [JUNK, BOARD, { ...BOARD, fileName: 'b2' }, XML, SEXPR, PRO, SCH]
    expect(assembleKicadInputs(everything)).toEqual({
      ok: false,
      error: SCHEMATIC_UNSUPPORTED_ERROR
    })
    expect(assembleKicadInputs(everything.filter((f) => f !== SCH))).toEqual({
      ok: false,
      error: PROJECT_UNSUPPORTED_ERROR
    })
    const noProject = everything.filter((f) => f !== SCH && f !== PRO)
    expect(assembleKicadInputs(noProject)).toEqual({ ok: false, error: MULTIPLE_NETLISTS_ERROR })
    const oneNetlist = noProject.filter((f) => f !== XML)
    expect(assembleKicadInputs(oneNetlist)).toEqual({ ok: false, error: MULTIPLE_BOARDS_ERROR })
    const oneBoard = oneNetlist.filter((f) => f.fileName !== 'b2')
    expect(assembleKicadInputs(oneBoard)).toEqual({ ok: false, error: UNRECOGNIZED_FILE_ERROR })
  })
})

describe('assembleExportInputs (provider dispatch)', () => {
  it('sniffs and routes for kicad', () => {
    expect(assembleExportInputs('kicad', [BOARD])).toEqual({ ok: true, inputs: { board: BOARD } })
    expect(assembleExportInputs('kicad', [SCH])).toEqual({
      ok: false,
      error: SCHEMATIC_UNSUPPORTED_ERROR
    })
  })

  it('hands any other provider exactly one file as the netlist, unsniffed', () => {
    const altium: EdaExportFile = { fileName: 'design.net', content: 'anything goes' }
    expect(assembleExportInputs('altium', [altium])).toEqual({
      ok: true,
      inputs: { netlist: altium }
    })
  })

  it('refuses more than one file for a single-file provider', () => {
    expect(assembleExportInputs('altium', [XML, SEXPR])).toEqual({
      ok: false,
      error: MULTIPLE_NETLISTS_ERROR
    })
  })

  it('refuses an empty pick for a single-file provider', () => {
    expect(assembleExportInputs('altium', [])).toEqual({ ok: false, error: NO_FILES_ERROR })
  })
})

describe('file-input shape per provider', () => {
  it('kicad accepts netlists and boards and allows several files', () => {
    expect(exportFileAccept('kicad')).toBe('.xml,.net,.kicad_pcb')
    expect(allowsMultipleFiles('kicad')).toBe(true)
  })

  it('other export providers keep the single netlist pick', () => {
    expect(exportFileAccept('altium')).toBe('.xml,.net')
    expect(allowsMultipleFiles('altium')).toBe(false)
  })

  it('kicad gets the netlist / board prompt with a hint; others keep the export prompt', () => {
    const kicad = exportFilePrompt('kicad')
    expect(kicad.button).toBe('Choose netlist / board file')
    expect(kicad.ariaLabel).toBe('Choose a netlist export or board file')
    expect(kicad.hint).toMatch(/kicad_pcb/)
    const altium = exportFilePrompt('altium')
    expect(altium.button).toBe('Choose export file')
    expect(altium.ariaLabel).toBe('Choose a committed netlist export')
    expect(altium.hint).toBeNull()
  })
})
