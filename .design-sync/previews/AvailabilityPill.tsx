import { AvailabilityPill } from '@solus/desktop'

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

const INSTALLED = { ...NOT_INSTALLED, installed: true, enabled: true, pinnedVersion: '1.2.0' }

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
      verified: true,
      ...catalog
    },
    manifest: null,
    state,
    availability,
    missing
  }
}

function StatusRow({ name, view }) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 24,
        width: 300
      }}
    >
      <span style={{ fontSize: 13, fontWeight: 600 }}>{name}</span>
      <AvailabilityPill view={view} />
    </div>
  )
}

export function Installed() {
  return (
    <StatusRow
      name="BOM"
      view={extensionView({ slug: 'bom', name: 'BOM', publisher: 'Solus' }, INSTALLED, 'installed')}
    />
  )
}

export function UpdateAvailable() {
  return (
    <StatusRow
      name="KiCad Viewer"
      view={extensionView(
        { slug: 'kicad-viewer', name: 'KiCad Viewer', publisher: 'Solus' },
        { ...INSTALLED, updateAvailable: { version: '2.1.0', widensPermissions: false } },
        'installed'
      )}
    />
  )
}

export function Available() {
  return (
    <StatusRow
      name="Telemetry Dashboard"
      view={extensionView(
        { slug: 'telemetry-dashboard', name: 'Telemetry Dashboard', publisher: 'Solus' },
        NOT_INSTALLED,
        'available'
      )}
    />
  )
}

export function NeedsSource() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <StatusRow
        name="Net Class Audit"
        view={extensionView(
          { slug: 'net-class-audit', name: 'Net Class Audit', publisher: 'Solus' },
          NOT_INSTALLED,
          'needs_source',
          [['eda']]
        )}
      />
      <StatusRow
        name="Harness Router"
        view={extensionView(
          { slug: 'harness-router', name: 'Harness Router', publisher: 'Ari Robotics' },
          NOT_INSTALLED,
          'needs_source',
          [['cad', 'eda']]
        )}
      />
      <StatusRow
        name="URDF Inspector"
        view={extensionView(
          { slug: 'urdf-inspector', name: 'URDF Inspector', publisher: 'Solus' },
          NOT_INSTALLED,
          'needs_source',
          [['cad'], ['runtime']]
        )}
      />
    </div>
  )
}

export function Blocked() {
  return (
    <StatusRow
      name="Firmware Flasher"
      view={extensionView(
        { slug: 'firmware-flasher', name: 'Firmware Flasher', publisher: 'bench-tools' },
        { ...NOT_INSTALLED, blocked: true },
        'blocked'
      )}
    />
  )
}
