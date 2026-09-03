// SOLUSDEV-235 — the in-repo extension catalog.
//
// This is BUILD-TIME data, like the widget manifests discovered by
// widgets/discover.ts — it describes what this build of Solus can offer, not
// what a server said. Every first-party entry names a capability that exists
// in the repo today (Live Bench telemetry, the MuJoCo scene, experiments,
// cross-domain findings, the CTR-04 impact result, ADR-029 recognition, the
// CTR-03 approval queue). Install counts are null: the SOLUSDEV-152 charter
// forbids fabricated numbers, so the header renders "— installs" until the
// catalog service reports real ones.
import type { ExtensionManifest } from './extension.types'

const SOLUS_DOCS = 'https://docs.solusforge.com/extensions'
const SOLUS_ISSUES = 'https://gitlab.com/solusforge/solus/-/issues'

const READ_GRAPH = { scope: 'graph.read', status: 'granted' } as const
const READ_TELEMETRY = { scope: 'telemetry.read', status: 'granted' } as const
const TELEMETRY_NOT_ASKED = { scope: 'telemetry.read', status: 'not_asked' } as const

export const EXTENSION_CATALOG: readonly ExtensionManifest[] = [
  {
    id: 'live-signals',
    name: 'Live Signals',
    publisher: 'solus',
    summary:
      'One widget per signal — value, rolling chart, anomaly markers, inline rename, unit conversion.',
    icon: 'wave',
    version: '1.0.0',
    updatedAt: '2026-08-19T00:00:00Z',
    installs: null,
    requires: [],
    contributions: [
      {
        kind: 'widget',
        title: 'Signal widgets',
        detail: 'One Live Bench widget per telemetry signal, added as streams appear.'
      },
      {
        kind: 'grounding',
        title: 'SOL grounding',
        detail: 'Recent signal values become part of what SOL can reason over.'
      }
    ],
    permissions: [READ_GRAPH, READ_TELEMETRY],
    credits: { thisCycle: null, perRun: null },
    links: { documentation: `${SOLUS_DOCS}/live-signals`, issues: SOLUS_ISSUES },
    defaultInstalled: true
  },
  {
    id: 'scene',
    name: 'Scene',
    publisher: 'solus',
    summary: 'Spawn connected robots and assemblies; mirrors real motion.',
    icon: 'diamond',
    version: '1.0.0',
    updatedAt: '2026-08-19T00:00:00Z',
    installs: null,
    requires: [],
    contributions: [
      {
        kind: 'widget',
        title: 'Scene widget',
        detail: 'A MuJoCo scene built from the project’s CAD/URDF, refreshed when CAD changes.'
      }
    ],
    permissions: [READ_GRAPH, READ_TELEMETRY],
    credits: { thisCycle: null, perRun: null },
    links: { documentation: `${SOLUS_DOCS}/scene`, issues: SOLUS_ISSUES },
    defaultInstalled: true
  },
  {
    id: 'experiments',
    name: 'Experiments',
    publisher: 'solus',
    summary: 'Define, run, record, play back and compare runs — sim and hardware.',
    icon: 'play',
    version: '1.0.0',
    updatedAt: '2026-08-19T00:00:00Z',
    installs: null,
    requires: [],
    contributions: [
      {
        kind: 'widget',
        title: 'Overview widget',
        detail: 'Appears on the project Overview once its source is connected.'
      },
      {
        kind: 'grounding',
        title: 'SOL grounding',
        detail: 'Its data becomes part of what SOL can reason over.'
      }
    ],
    permissions: [READ_GRAPH, TELEMETRY_NOT_ASKED],
    credits: { thisCycle: null, perRun: 1 },
    links: {
      documentation: `${SOLUS_DOCS}/experiments`,
      source: 'https://gitlab.com/solusforge/solus',
      issues: SOLUS_ISSUES
    },
    defaultInstalled: true
  },
  {
    id: 'cross-domain-findings',
    name: 'Cross-domain Findings',
    publisher: 'solus',
    summary:
      'Explanations that span mechanical, electrical and software — what happened, why, what to do.',
    icon: 'triangle',
    version: '1.0.0',
    updatedAt: '2026-08-19T00:00:00Z',
    installs: null,
    requires: [],
    contributions: [
      {
        kind: 'panel',
        title: 'Findings panel',
        detail: 'Every finding names the entities it spans and the fix it proposes.'
      },
      {
        kind: 'grounding',
        title: 'SOL grounding',
        detail: 'Open findings are context for every SOL turn in the project.'
      }
    ],
    permissions: [READ_GRAPH, { scope: 'findings.write', status: 'granted' }],
    credits: { thisCycle: null, perRun: 2 },
    links: { documentation: `${SOLUS_DOCS}/findings`, issues: SOLUS_ISSUES },
    defaultInstalled: true
  },
  {
    id: 'impact-map',
    name: 'Impact Map',
    publisher: 'solus',
    summary: 'What a change touches across code, electronics and CAD before it ships.',
    icon: 'graph',
    version: '1.0.0',
    updatedAt: '2026-08-19T00:00:00Z',
    installs: null,
    requires: [],
    contributions: [
      {
        kind: 'widget',
        title: 'Impact widget',
        detail: 'Ranks the entities downstream of the focused change by severity.'
      }
    ],
    permissions: [READ_GRAPH],
    credits: { thisCycle: null, perRun: null },
    links: { documentation: `${SOLUS_DOCS}/impact`, issues: SOLUS_ISSUES },
    defaultInstalled: true
  },
  {
    id: 'runtime-recognition',
    name: 'Runtime Recognition',
    publisher: 'solus',
    summary: 'Names what the robot is doing from camera and telemetry; proposes graph links.',
    icon: 'sol',
    version: '1.0.0',
    updatedAt: '2026-08-19T00:00:00Z',
    installs: null,
    requires: [['runtime']],
    contributions: [
      {
        kind: 'panel',
        title: 'Recognition proposals',
        detail: 'Proposed identity links you confirm or reject; confirmations land in the graph.'
      }
    ],
    permissions: [READ_GRAPH, READ_TELEMETRY],
    credits: { thisCycle: null, perRun: 3 },
    links: { documentation: `${SOLUS_DOCS}/recognition`, issues: SOLUS_ISSUES },
    defaultInstalled: true
  },
  {
    id: 'approval-queue',
    name: 'Approval Queue',
    publisher: 'solus',
    summary: 'Every action that would touch hardware or an external tool waits here for a human.',
    icon: 'check',
    version: '1.0.0',
    updatedAt: '2026-08-19T00:00:00Z',
    installs: null,
    requires: [],
    contributions: [
      {
        kind: 'panel',
        title: 'Approvals panel',
        detail: 'Shows the concrete action, its diff, and who approved it.'
      }
    ],
    permissions: [READ_GRAPH],
    credits: { thisCycle: null, perRun: null },
    links: { documentation: `${SOLUS_DOCS}/approvals`, issues: SOLUS_ISSUES },
    defaultInstalled: true
  },
  {
    id: 'bom',
    name: 'BOM',
    publisher: 'solus',
    summary:
      'Bill of materials from your EDA project — sourcing status, findings flag affected lines.',
    icon: 'lines',
    version: '0.9.0',
    updatedAt: '2026-08-05T00:00:00Z',
    installs: null,
    requires: [['eda']],
    contributions: [
      {
        kind: 'widget',
        title: 'BOM widget',
        detail: 'Every line item linked to its schematic symbol and graph entity.'
      },
      {
        kind: 'check',
        title: 'Sourcing check',
        detail: 'Flags lines whose part is end-of-life or unavailable.'
      }
    ],
    permissions: [READ_GRAPH, { scope: 'sources.read', status: 'granted' }],
    credits: { thisCycle: null, perRun: null },
    links: { documentation: `${SOLUS_DOCS}/bom`, issues: SOLUS_ISSUES },
    defaultInstalled: false
  },
  {
    id: 'can-telemetry',
    name: 'CAN Telemetry',
    publisher: 'solus',
    summary: 'Bus load, node health, fault frames — live or from logs.',
    icon: 'wave',
    version: '0.8.0',
    updatedAt: '2026-08-12T00:00:00Z',
    installs: null,
    requires: [['canbus']],
    contributions: [
      {
        kind: 'widget',
        title: 'CAN bus widget',
        detail: 'Per-node health and bus load; fault frames become findings.'
      }
    ],
    permissions: [READ_GRAPH, READ_TELEMETRY],
    credits: { thisCycle: null, perRun: null },
    links: { documentation: `${SOLUS_DOCS}/can`, issues: SOLUS_ISSUES },
    defaultInstalled: false
  },
  {
    id: 'datasheet-finder',
    name: 'Datasheet Finder',
    publisher: 'community',
    summary: 'Looks up datasheets for parts in your schematic and pins them to graph nodes.',
    icon: 'lines',
    version: '0.3.1',
    updatedAt: '2026-07-28T00:00:00Z',
    installs: null,
    requires: [['eda']],
    contributions: [
      {
        kind: 'panel',
        title: 'Datasheet panel',
        detail: 'Pinned datasheets appear on the part’s entity in the Context Model.'
      }
    ],
    permissions: [READ_GRAPH, { scope: 'sources.read', status: 'not_asked' }],
    credits: { thisCycle: null, perRun: 1 },
    links: {
      documentation: 'https://github.com/solus-community/datasheet-finder#readme',
      source: 'https://github.com/solus-community/datasheet-finder',
      issues: 'https://github.com/solus-community/datasheet-finder/issues'
    },
    defaultInstalled: false
  },
  {
    id: 'fsae-rules-checker',
    name: 'FSAE Rules Checker',
    publisher: 'community',
    summary: 'Checks EV rules against your CAD and schematic — wire gauges, fusing, insulation.',
    icon: 'check',
    version: '0.5.0',
    updatedAt: '2026-08-01T00:00:00Z',
    installs: null,
    requires: [['cad', 'eda']],
    contributions: [
      {
        kind: 'check',
        title: 'EV rules checks',
        detail: 'One check per rule; violations become cross-domain findings.'
      }
    ],
    permissions: [READ_GRAPH, { scope: 'findings.write', status: 'not_asked' }],
    credits: { thisCycle: null, perRun: 2 },
    links: {
      documentation: 'https://github.com/solus-community/fsae-rules#readme',
      source: 'https://github.com/solus-community/fsae-rules',
      issues: 'https://github.com/solus-community/fsae-rules/issues'
    },
    defaultInstalled: false
  }
]

/** Catalog lookup by id; null for an id this build does not know. */
export function findExtension(id: string): ExtensionManifest | null {
  return EXTENSION_CATALOG.find((m) => m.id === id) ?? null
}
