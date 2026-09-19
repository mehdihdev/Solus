import { Avatar, Card, KV, Mono } from '@solus/desktop'

const row = { display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' } as const
const person = { display: 'flex', gap: 10, alignItems: 'center', marginBottom: 10 } as const
const name = { fontSize: 13, color: 'var(--tx)' } as const
const meta = { fontSize: 11.5, color: 'var(--mut)' } as const

export function Sizes() {
  return (
    <div style={row}>
      <Avatar name="Priya Raman" size={20} />
      <Avatar name="Marcus Webb" size={26} />
      <Avatar name="Jae Lin" size={28} />
      <Avatar name="Ana Ruiz" size={42} />
    </div>
  )
}

export function TeamRoster() {
  return (
    <Card style={{ width: 340 }}>
      <Mono>ARI-02 · 5 MEMBERS</Mono>
      <div style={{ marginTop: 12 }}>
        <div style={person}>
          <Avatar name="Priya Raman" size={28} />
          <div>
            <div style={name}>Priya Raman</div>
            <div style={meta}>Owner · firmware</div>
          </div>
        </div>
        <div style={person}>
          <Avatar name="Marcus Webb" size={28} />
          <div>
            <div style={name}>Marcus Webb</div>
            <div style={meta}>Admin · KiCad, power</div>
          </div>
        </div>
        <div style={person}>
          <Avatar name="Sofia Duarte" size={28} />
          <div>
            <div style={name}>Sofia Duarte</div>
            <div style={meta}>Member · Onshape chassis</div>
          </div>
        </div>
        <div style={person}>
          <Avatar name="Kenji Ito" size={28} />
          <div>
            <div style={name}>Kenji Ito</div>
            <div style={meta}>Member · ROS perception</div>
          </div>
        </div>
        <div style={{ ...person, marginBottom: 0 }}>
          <Avatar name="Rafael Ortiz" size={28} />
          <div>
            <div style={name}>Rafael Ortiz</div>
            <div style={meta}>Member · Jetson deploys</div>
          </div>
        </div>
      </div>
    </Card>
  )
}

export function ActivityFeed() {
  return (
    <Card style={{ width: 380 }}>
      <Mono>ACTIVITY</Mono>
      <div style={{ marginTop: 12 }}>
        <div style={person}>
          <Avatar name="Jae Lin" />
          <div style={meta}>
            <span style={name}>Jae Lin</span> re-synced KiCad — 14 entities changed
          </div>
        </div>
        <div style={person}>
          <Avatar name="Ana Ruiz" />
          <div style={meta}>
            <span style={name}>Ana Ruiz</span> confirmed OV9281_IC ↔ camera_node
          </div>
        </div>
        <div style={{ ...person, marginBottom: 0 }}>
          <Avatar name="Marcus Webb" />
          <div style={meta}>
            <span style={name}>Marcus Webb</span> flashed firmware to Ari-02
          </div>
        </div>
      </div>
    </Card>
  )
}

export function WithDetails() {
  return (
    <Card style={{ width: 320 }}>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 14 }}>
        <Avatar name="Priya Raman" size={42} />
        <div>
          <div style={{ fontSize: 14, fontWeight: 600 }}>Priya Raman</div>
          <div style={meta}>priya@ari-robotics.dev</div>
        </div>
      </div>
      <KV k="Role" v="Owner" />
      <KV k="Team" v="Ari Robotics" />
      <KV k="Joined" v="March 2024" />
    </Card>
  )
}
