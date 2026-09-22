import { SolusComposer } from '@solus/desktop'

const noop = (): void => {}
const noopAsync = async (): Promise<void> => {}

const box = { width: 320 } as const

export function AskSol() {
  return (
    <div style={box}>
      <SolusComposer kind="ask" initial="" onCancel={noop} onSubmit={noopAsync} />
    </div>
  )
}

export function TypeNote() {
  return (
    <div style={box}>
      <SolusComposer kind="type" initial="" onCancel={noop} onSubmit={noopAsync} />
    </div>
  )
}

export function EditNote() {
  return (
    <div style={box}>
      <SolusComposer
        kind="edit"
        initial="Fuse the 24 V rail at 15 A — FSAE EV rules cap it below the motor stall draw."
        onCancel={noop}
        onSubmit={noopAsync}
      />
    </div>
  )
}
