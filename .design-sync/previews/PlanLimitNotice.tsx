import { Card, Mono, PlanLimitNotice } from '@solus/desktop'

const noop = (): void => {}

export function WithUpgrade() {
  return (
    <div style={{ width: 460 }}>
      <PlanLimitNotice
        message="You're at your collaborative-team limit — Individual plans include 1 teammate. Upgrade to Teams to invite the rest of the lab."
        onUpgrade={noop}
      />
    </div>
  )
}

export function Standalone() {
  return (
    <div style={{ width: 460 }}>
      <PlanLimitNotice message="Your plan allows 3 connected sources. Disconnect one before adding the Onshape document." />
    </div>
  )
}

export function Compact() {
  return (
    <Card pad={18} style={{ width: 460 }}>
      <Mono>ARI-02 · TEAM</Mono>
      <div style={{ fontSize: 12.5, margin: '10px 0 8px' }}>3 of 3 seats used</div>
      <PlanLimitNotice
        compact
        message="You're at your seat limit. Upgrade to add another engineer."
        onUpgrade={noop}
      />
    </Card>
  )
}

export function InModal() {
  return (
    <Card pad={20} style={{ width: 400 }}>
      <Mono>NEW PROJECT</Mono>
      <div style={{ fontSize: 12.5, color: 'var(--mut)', marginTop: 8, lineHeight: 1.6 }}>
        A project holds one robot's graph, its sources, and its checks.
      </div>
      <PlanLimitNotice
        message="Individual plans include 2 projects. Ari-01 and Ari-02 already use both."
        onUpgrade={noop}
      />
    </Card>
  )
}
