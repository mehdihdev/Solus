import { RegionCard } from '@solus/desktop'

const noop = (): void => {}

const CROP_PNG =
  'iVBORw0KGgoAAAANSUhEUgAAACAAAAAUCAIAAABj86gYAAAAOUlEQVR42mOQllWgKWIYRhaczLeiIhqWFgz9SDYwtiAGQRRb2bngR6MW0NwCmkfyqAU0sWC0wsGBAKv1YcvpqSRIAAAAAElFTkSuQmCC'

const box = { width: 360 } as const

export function CircledRegion() {
  return (
    <div style={box}>
      <RegionCard
        region={{
          pngBase64: CROP_PNG,
          contextPngBase64: CROP_PNG,
          width: 320,
          height: 200,
          source: { app: 'Onshape', title: 'Ari-02 chassis — camera bracket v3' },
          capturedAt: 1758115200000
        }}
        onAsk={noop}
      />
    </div>
  )
}

export function UnknownWindow() {
  return (
    <div style={box}>
      <RegionCard
        region={{
          pngBase64: CROP_PNG,
          contextPngBase64: CROP_PNG,
          width: 320,
          height: 200,
          source: null,
          capturedAt: 1758115260000
        }}
        onAsk={noop}
      />
    </div>
  )
}

export function SchematicCrop() {
  return (
    <div style={box}>
      <RegionCard
        region={{
          pngBase64: CROP_PNG,
          contextPngBase64: CROP_PNG,
          width: 320,
          height: 200,
          source: { app: 'KiCad', title: 'main-board.kicad_pcb — U4 DRV8301' },
          capturedAt: 1758115320000
        }}
        onAsk={noop}
      />
    </div>
  )
}
