import { TwoStepDelete } from '@solus/desktop'

const noop = (): void => {}
const noopAsync = async (): Promise<void> => {}
const box = { width: 380 } as const

export function Idle() {
  return (
    <div style={box}>
      <TwoStepDelete
        label="Delete robot"
        detail="Removes Ari-02 and every entity synced from it."
        armed={false}
        onArm={noop}
        onDisarm={noop}
        onConfirm={noopAsync}
      />
    </div>
  )
}

export function Armed() {
  return (
    <div style={box}>
      <TwoStepDelete
        label="Delete robot"
        detail="Removes Ari-02 and every entity synced from it."
        armed
        onArm={noop}
        onDisarm={noop}
        onConfirm={noopAsync}
      />
    </div>
  )
}

export function Busy() {
  return (
    <div style={box}>
      <TwoStepDelete
        label="Delete robot"
        detail="Removes Ari-02 and every entity synced from it."
        armed
        busy
        onArm={noop}
        onDisarm={noop}
        onConfirm={noopAsync}
      />
    </div>
  )
}

export function WithError() {
  return (
    <div style={box}>
      <TwoStepDelete
        label="Delete robot"
        detail="Removes Ari-02 and every entity synced from it."
        armed
        error="Robot is referenced by 3 open checks — resolve them first."
        onArm={noop}
        onDisarm={noop}
        onConfirm={noopAsync}
      />
    </div>
  )
}
