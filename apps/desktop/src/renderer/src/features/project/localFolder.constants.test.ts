// SOLUSDEV-249 (I2) — the pure words and decisions behind the LOCAL FOLDER card.
import { describe, expect, it } from 'vitest'
import type { Source } from '../../lib/api/resources'
import type { DetectedProject, LocalFolderView } from '../../lib/api/resources.localfolder'
import {
  API_UNREACHABLE_NOTE,
  COMPANION_OFFLINE_NOTE,
  COMPANION_RECONNECTING_NOTE,
  NOT_SCANNED_NOTE,
  OPEN_LABEL,
  VSCODE_MISSING_NOTE,
  detectedProjects,
  editorDisabledReason,
  folderBasename,
  isLocalEntityKind,
  linkedFolderPresentation,
  rootProject,
  scanState,
  toolMark
} from './localFolder.constants'

const source = (over: Partial<Source>): Source => ({
  id: 's1',
  project_id: 'p1',
  type: 'local',
  name: 'mehdi-mbp',
  status: 'connected',
  config: {},
  account_login: null,
  last_synced_at: null,
  last_error: null,
  created_at: '',
  updated_at: '',
  ...over
})

const row = (over: Partial<DetectedProject>): DetectedProject => ({
  entity_id: 'e-kicad',
  entity_key: 'kicad:hw/main',
  tool: 'kicad',
  name: 'main',
  path: 'hw/main/main.kicad_pro',
  open_targets: ['kicad', 'vscode', 'system'],
  ...over
})

const ROOT = row({
  entity_id: 'e-root',
  entity_key: 'clone:',
  tool: 'clone',
  name: 'rover-fw',
  path: '',
  open_targets: ['vscode', 'system']
})

const view = (over: Partial<LocalFolderView>): LocalFolderView => ({
  source: source({}),
  bridge: { connected: true, tools_installed: { kicad: true, vscode: true } },
  detected: [ROOT, row({})],
  ...over
})

describe('folderBasename', () => {
  it('takes the last segment on either separator, ignoring a trailing one', () => {
    expect(folderBasename('/home/u/rover-fw')).toBe('rover-fw')
    expect(folderBasename('/home/u/rover-fw/')).toBe('rover-fw')
    expect(folderBasename('C:\\Users\\u\\rover-fw')).toBe('rover-fw')
    expect(folderBasename('/')).toBe('/')
  })
})

describe('scanState', () => {
  const NOW = Date.parse('2026-09-07T12:00:00Z')

  it('says nothing without a source', () => {
    expect(scanState(null, NOW)).toBeNull()
  })

  it('is scanning while the source syncs', () => {
    expect(scanState(source({ status: 'syncing' }), NOW)).toEqual({
      kind: 'scanning',
      text: 'Scanning…'
    })
  })

  it('reports when the last scan landed', () => {
    const synced = source({ status: 'connected', last_synced_at: '2026-09-07T11:48:00Z' })
    expect(scanState(synced, NOW)).toEqual({ kind: 'scanned', text: 'Scanned 12 min ago' })
  })

  it('shows the error message verbatim', () => {
    const failed = source({
      status: 'error',
      last_error: { code: 'api_unreachable', message: 'No companion session for this machine' }
    })
    expect(scanState(failed, NOW)).toEqual({
      kind: 'error',
      text: 'No companion session for this machine'
    })
  })

  it('says nothing for a connected source that has not scanned yet', () => {
    expect(scanState(source({ status: 'connected' }), NOW)).toBeNull()
  })
})

describe('detected projects', () => {
  it('separates the root from the projects inside it', () => {
    const v = view({})
    expect(rootProject(v)?.entity_id).toBe('e-root')
    expect(detectedProjects(v).map((d) => d.entity_id)).toEqual(['e-kicad'])
    expect(rootProject(null)).toBeNull()
    expect(detectedProjects(null)).toEqual([])
  })
})

describe('editorDisabledReason', () => {
  it('is null when the root opens in VS Code', () => {
    expect(editorDisabledReason(view({}), 'ready')).toBeNull()
  })

  it('names the offline companion before anything else', () => {
    const v = view({ bridge: { connected: false, tools_installed: { vscode: true } } })
    expect(editorDisabledReason(v, 'ready')).toBe(COMPANION_OFFLINE_NOTE)
  })

  it('says VS Code is missing when the scan probed it false', () => {
    const v = view({
      bridge: { connected: true, tools_installed: { vscode: false } },
      detected: [{ ...ROOT, open_targets: ['system'] }]
    })
    expect(editorDisabledReason(v, 'ready')).toBe(VSCODE_MISSING_NOTE)
  })

  it('waits for the first scan, and is honest when the API is unreachable', () => {
    expect(editorDisabledReason(view({ detected: [] }), 'ready')).toBe(NOT_SCANNED_NOTE)
    expect(editorDisabledReason(null, 'loading')).toBe(COMPANION_RECONNECTING_NOTE)
    expect(editorDisabledReason(null, 'offline')).toBe(API_UNREACHABLE_NOTE)
  })
})

describe('tool presentation', () => {
  it('labels every open target', () => {
    expect(OPEN_LABEL).toEqual({
      kicad: 'Open in KiCad',
      altium: 'Open in Altium',
      vscode: 'Open in editor',
      system: 'Open'
    })
  })

  it('marks tools with their domain colour and falls back to two letters', () => {
    expect(toolMark('kicad')).toEqual({ mark: 'Ki', color: 'var(--ee)' })
    expect(toolMark('altium')).toEqual({ mark: 'Al', color: 'var(--ee)' })
    expect(toolMark('cad')).toEqual({ mark: 'CA', color: 'var(--me)' })
    expect(toolMark('arduino')).toEqual({ mark: 'Ar', color: 'var(--sw)' })
    expect(toolMark('python')).toEqual({ mark: 'Py', color: 'var(--sw)' })
    expect(toolMark('zig')).toEqual({ mark: 'ZI', color: 'var(--mut)' })
  })

  it('knows which graph kinds a local folder can open', () => {
    for (const kind of [
      'kicad_project',
      'altium_project',
      'cad_folder',
      'arduino_sketch',
      'python_code',
      'local_clone',
      'local_folder'
    ]) {
      expect(isLocalEntityKind(kind)).toBe(true)
    }
    expect(isLocalEntityKind('part')).toBe(false)
  })
})

describe('linkedFolderPresentation', () => {
  it('opens the root in the editor and calls a finished scan scanned', () => {
    const v = view({ source: source({ last_synced_at: '2026-09-07T11:00:00Z' }) })
    expect(linkedFolderPresentation(v, 'ready')).toEqual({
      editorReason: null,
      rootEntityId: 'e-root',
      bridgeOffline: false,
      rowsReason: null,
      scanned: true
    })
  })

  it('disables rows and the editor together while the companion is offline', () => {
    const v = view({ bridge: { connected: false, tools_installed: {} } })
    const out = linkedFolderPresentation(v, 'ready')
    expect(out.bridgeOffline).toBe(true)
    expect(out.rowsReason).toBe(COMPANION_OFFLINE_NOTE)
    expect(out.editorReason).toBe(COMPANION_OFFLINE_NOTE)
    expect(out.scanned).toBe(false)
  })

  it('is not "offline" before the source exists', () => {
    const out = linkedFolderPresentation(null, 'offline')
    expect(out.bridgeOffline).toBe(false)
    expect(out.rootEntityId).toBeNull()
    expect(out.rowsReason).toBe(API_UNREACHABLE_NOTE)
  })
})

describe('rowsDisabledReason', () => {
  it('does not disable a row for a missing VS Code when the bridge is connected', async () => {
    const { rowsDisabledReason, linkedFolderPresentation, VSCODE_MISSING_NOTE } =
      await import('./localFolder.constants')
    const view = {
      source: { status: 'connected', last_synced_at: '2026-09-07T00:00:00Z' },
      bridge: { connected: true, tools_installed: { kicad: true, vscode: false } },
      detected: [
        {
          entity_id: 'r',
          entity_key: 'clone:',
          tool: 'root',
          name: 'x',
          path: '.',
          open_targets: ['system']
        },
        {
          entity_id: 'k',
          entity_key: 'kicad:hw',
          tool: 'kicad',
          name: 'hw',
          path: 'hw/hw.kicad_pro',
          open_targets: ['kicad', 'system']
        }
      ]
    } as never
    expect(rowsDisabledReason(view, 'ready')).toBeNull()
    const out = linkedFolderPresentation(view, 'ready')
    expect(out.rowsReason).toBeNull()
    expect(out.editorReason).toBe(VSCODE_MISSING_NOTE)
  })
})

it('keeps every open control disabled during reconnection even with a previous connected view', () => {
  const presentation = linkedFolderPresentation(view({}), 'loading')
  expect(presentation.bridgeOffline).toBe(false)
  expect(presentation.rowsReason).toBe(COMPANION_RECONNECTING_NOTE)
  expect(presentation.editorReason).toBe(COMPANION_RECONNECTING_NOTE)
})
