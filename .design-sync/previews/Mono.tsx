import { Card, KV, Mono } from '@solus/desktop'

const stack = { display: 'grid', gap: 10, alignItems: 'start' } as const

export function Sizes() {
  return (
    <div style={stack}>
      <Mono size={7.5}>MENU CAPTION · 7.5</Mono>
      <Mono size={9.5}>FIELD LABEL · 9.5</Mono>
      <Mono size={10}>SECTION LABEL · 10</Mono>
      <Mono size={13}>PANEL HEADING · 13</Mono>
    </div>
  )
}

export function Colors() {
  return (
    <div style={stack}>
      <Mono>SYNC IDLE</Mono>
      <Mono color="var(--tx)">GRAPH ENTITY</Mono>
      <Mono color="var(--acc)">SOL · EXPERT MODE</Mono>
      <Mono color="var(--ok)">ALL CHECKS PASSED</Mono>
      <Mono color="var(--warn)">3 OPEN WARNINGS</Mono>
      <Mono color="var(--err)">PROVING FAILED</Mono>
    </div>
  )
}

export function DomainLabels() {
  return (
    <div style={stack}>
      <Mono color="var(--sw)">SOFTWARE · 212 ENTITIES</Mono>
      <Mono color="var(--ee)">ELECTRICAL · 88 ENTITIES</Mono>
      <Mono color="var(--me)">MECHANICAL · 41 ENTITIES</Mono>
      <Mono color="var(--rt)">RUNTIME · 17 SIGNALS</Mono>
    </div>
  )
}

export function Tracking() {
  return (
    <div style={stack}>
      <Mono ls="0.02em">TIGHT · I2C-1 @ 0X60</Mono>
      <Mono ls="0.1em">DEFAULT · I2C-1 @ 0X60</Mono>
      <Mono ls="0.24em">WIDE · I2C-1 @ 0X60</Mono>
    </div>
  )
}

export function AsCardLabel() {
  return (
    <Card style={{ width: 320 }}>
      <Mono>JETSON ORIN NANO · DEPLOY TARGET</Mono>
      <div style={{ marginTop: 12 }}>
        <KV k="Address" v="ari-02.local" />
        <KV k="JetPack" v="6.0" />
        <KV k="CUDA" v="11.8 — needs 12" vColor="var(--err)" />
      </div>
      <div style={{ marginTop: 12 }}>
        <Mono size={9.5} color="var(--mut)">LAST DEPLOY 2 DAYS AGO</Mono>
      </div>
    </Card>
  )
}
