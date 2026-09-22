import { ExtensionCard } from '@solus/desktop'

const noop = (): void => {}

const NOT_INSTALLED = {
  installed: false,
  enabled: false,
  settings: {},
  grantedScopes: [],
  grantedNetwork: [],
  pinnedVersion: null,
  updateAvailable: null,
  blocked: false
}

const INSTALLED = {
  ...NOT_INSTALLED,
  installed: true,
  enabled: true,
  settings: { refresh: 'hourly' },
  grantedScopes: ['graph.read', 'sources.read'],
  grantedNetwork: ['https://api.octopart.com'],
  pinnedVersion: '1.2.0'
}

function extensionView(catalog, state, availability, missing = []) {
  return {
    catalog: {
      installCount: 412,
      latestVersion: '1.2.0',
      updatedAt: '2026-09-01T09:12:03.000Z',
      requires: [['eda']],
      views: ['widget', 'page'],
      assetUrls: { icon: null, privacyPolicy: null },
      inCatalog: true,
      ...catalog
    },
    manifest: null,
    state,
    availability,
    missing
  }
}

const bom = extensionView(
  {
    slug: 'bom',
    name: 'BOM',
    summary: 'Bill of materials from your EDA project, priced against Octopart.',
    publisher: 'Solus',
    verified: true
  },
  INSTALLED,
  'installed'
)

const kicadViewer = extensionView(
  {
    slug: 'kicad-viewer',
    name: 'KiCad Viewer',
    summary: 'Open the board and schematic of any EDA source beside the graph.',
    publisher: 'Solus',
    verified: true
  },
  { ...INSTALLED, updateAvailable: { version: '2.1.0', widensPermissions: true } },
  'installed'
)

const telemetry = extensionView(
  {
    slug: 'telemetry-dashboard',
    name: 'Telemetry Dashboard',
    summary: 'Live signal tiles for Ari-02 — joint currents, bus voltage, ROS node health.',
    publisher: 'bench-tools',
    verified: false
  },
  NOT_INSTALLED,
  'available'
)

const harness = extensionView(
  {
    slug: 'harness-router',
    name: 'Harness Router',
    summary: 'Routes the wire harness through the chassis and flags clearance conflicts.',
    publisher: 'Ari Robotics',
    verified: false,
    requires: [['cad', 'eda']]
  },
  NOT_INSTALLED,
  'needs_source',
  [['cad', 'eda']]
)

const flasher = extensionView(
  {
    slug: 'firmware-flasher',
    name: 'Firmware Flasher',
    summary: 'Flashes Arduino targets straight from a build artifact.',
    publisher: 'bench-tools',
    verified: false
  },
  { ...NOT_INSTALLED, blocked: true },
  'blocked'
)

export function GridInstalled() {
  return (
    <div style={{ width: 380 }}>
      <ExtensionCard view={bom} layout="grid" onOpen={noop} />
    </div>
  )
}

export function GridCommunity() {
  return (
    <div style={{ width: 380 }}>
      <ExtensionCard view={telemetry} layout="grid" onOpen={noop} />
    </div>
  )
}

export function GridNeedsSource() {
  return (
    <div style={{ width: 380 }}>
      <ExtensionCard view={harness} layout="grid" onOpen={noop} />
    </div>
  )
}

export function ListLayout() {
  return (
    <div style={{ width: 460, display: 'flex', flexDirection: 'column', gap: 8 }}>
      <ExtensionCard view={bom} layout="list" onOpen={noop} />
      <ExtensionCard view={kicadViewer} layout="list" onOpen={noop} />
      <ExtensionCard view={telemetry} layout="list" onOpen={noop} />
      <ExtensionCard view={flasher} layout="list" onOpen={noop} />
    </div>
  )
}

export function GridSection() {
  return (
    <div
      style={{
        width: 780,
        display: 'grid',
        gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
        gap: 12
      }}
    >
      <ExtensionCard view={bom} layout="grid" onOpen={noop} />
      <ExtensionCard view={kicadViewer} layout="grid" onOpen={noop} />
      <ExtensionCard view={telemetry} layout="grid" onOpen={noop} />
      <ExtensionCard view={harness} layout="grid" onOpen={noop} />
    </div>
  )
}
