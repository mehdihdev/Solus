import { Card, KV, Mono, SolusLogo } from '@solus/desktop'

const row = { display: 'flex', gap: 24, alignItems: 'flex-end', flexWrap: 'wrap' } as const
const cap = { fontSize: 11, color: 'var(--mut)', marginTop: 8, textAlign: 'center' } as const

export function Sizes() {
  return (
    <div style={row}>
      <div>
        <SolusLogo size={20} />
        <div style={cap}>20 · rail</div>
      </div>
      <div>
        <SolusLogo size={30} />
        <div style={cap}>30 · settings</div>
      </div>
      <div>
        <SolusLogo size={52} />
        <div style={cap}>52 · wizard</div>
      </div>
      <div>
        <SolusLogo size={96} />
        <div style={cap}>96 · splash</div>
      </div>
    </div>
  )
}

export function OnSurfaces() {
  return (
    <div style={{ display: 'flex', gap: 14, alignItems: 'center', flexWrap: 'wrap' }}>
      <Card pad={20} style={{ background: 'var(--bg)' }}>
        <SolusLogo size={48} />
      </Card>
      <Card pad={20}>
        <SolusLogo size={48} />
      </Card>
      <Card pad={20} style={{ background: 'var(--sur2)' }}>
        <SolusLogo size={48} />
      </Card>
    </div>
  )
}

export function BrandLockup() {
  return (
    <Card style={{ width: 340 }}>
      <div style={{ display: 'flex', gap: 14, alignItems: 'center' }}>
        <SolusLogo size={52} />
        <div>
          <div style={{ fontSize: 18, fontWeight: 700, letterSpacing: '0.12em' }}>SOLUS</div>
          <div style={{ fontSize: 11.5, color: 'var(--mut)', marginTop: 3 }}>
            Robotics Context Model
          </div>
        </div>
      </div>
      <div style={{ marginTop: 16 }}>
        <KV k="Version" v="0.14.2" />
        <KV k="Workspace" v="Ari Robotics" />
        <KV k="Graph" v="358 entities · 611 relations" />
      </div>
    </Card>
  )
}

export function WizardHeader() {
  return (
    <Card pad={28} style={{ width: 380, textAlign: 'center' }}>
      <div style={{ display: 'flex', justifyContent: 'center' }}>
        <SolusLogo size={52} />
      </div>
      <div style={{ fontSize: 15, fontWeight: 600, marginTop: 16 }}>Connect your first source</div>
      <div style={{ fontSize: 12.5, color: 'var(--mut)', marginTop: 8, lineHeight: 1.55 }}>
        Point Solus at a GitHub repo, a KiCad project, an Onshape document or a ROS workspace. The
        graph builds itself from there.
      </div>
      <div style={{ marginTop: 18 }}>
        <Mono size={9.5}>STEP 1 OF 3</Mono>
      </div>
    </Card>
  )
}
