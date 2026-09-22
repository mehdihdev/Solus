import { Card, KV, Mono } from '@solus/desktop'

export function PartSpec() {
  return (
    <Card style={{ width: 320 }}>
      <Mono>OV9281 · GLOBAL SHUTTER SENSOR</Mono>
      <div style={{ marginTop: 12 }}>
        <KV k="Manufacturer" v="OmniVision" />
        <KV k="Package" v="CSP-38" />
        <KV k="Interface" v="MIPI CSI-2" />
        <KV k="Supply" v="2.8 V / 1.8 V" />
        <KV k="I²C address" v="0x60" />
      </div>
    </Card>
  )
}

export function StatusValues() {
  return (
    <Card style={{ width: 320 }}>
      <Mono>PRE-FLIGHT CHECKS</Mono>
      <div style={{ marginTop: 12 }}>
        <KV k="Power budget" v="within limits" vColor="var(--ok)" />
        <KV k="I²C collisions" v="1 conflict" vColor="var(--warn)" />
        <KV k="CUDA version" v="11.8 — needs 12" vColor="var(--err)" />
        <KV k="Last sync" v="4 minutes ago" />
      </div>
    </Card>
  )
}
