import { Card, ExtensionCard, KV, SectionLabel } from '@solus/desktop'

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
  { ...NOT_INSTALLED, installed: true, enabled: true, pinnedVersion: '1.2.0' },
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

export function StoreSections() {
  return (
    <div style={{ width: 440 }}>
      <SectionLabel>Installed</SectionLabel>
      <ExtensionCard view={bom} layout="list" onOpen={noop} />
      <SectionLabel>Popular in robotics</SectionLabel>
      <ExtensionCard view={telemetry} layout="list" onOpen={noop} />
    </div>
  )
}

export function DetailSections() {
  return (
    <div style={{ width: 400 }}>
      <SectionLabel>What it adds</SectionLabel>
      <Card>
        <KV k="Widget" v="Live Bench canvas" />
        <KV k="Page: BOM" v="Full-page view in the rail" />
        <KV k="Permissions" v="2 scopes · 1 network origin" />
      </Card>
      <SectionLabel>Requires</SectionLabel>
      <Card>
        <KV k="An EDA source (KiCad, Altium)" v="connected" vColor="var(--ok)" />
        <KV k="A runtime source (ROS, serial)" v="not connected" vColor="var(--warn)" />
      </Card>
    </div>
  )
}

export function VersionSection() {
  return (
    <div style={{ width: 400 }}>
      <SectionLabel>Version</SectionLabel>
      <Card>
        <KV k="Installed" v="1.2.0" />
        <KV k="Latest approved" v="2.1.0" vColor="var(--acc)" />
        <KV k="Publisher" v="Solus" />
        <KV k="Installs" v="412 installs" />
      </Card>
    </div>
  )
}
