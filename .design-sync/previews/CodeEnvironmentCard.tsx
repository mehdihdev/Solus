import { Card, CodeEnvironmentCard, Mono } from '@solus/desktop'

const box = { width: 320 } as const

/** `.solus-entry-content` is capped at 55px because it lives inside a graph
 *  node, so each payload here is the size a real node entry carries. */
function Entry({ caption, children }: { caption: string; children: React.ReactNode }) {
  return (
    <Card style={box}>
      <Mono>{caption}</Mono>
      <div style={{ marginTop: 10 }}>{children}</div>
    </Card>
  )
}

export function PythonVenv() {
  return (
    <Entry caption="ARI-FIRMWARE · CODE ENVIRONMENT">
      <CodeEnvironmentCard
        payload={{
          type: 'python',
          name: 'ari-perception',
          path: '.venv',
          interpreter: 'python 3.12.4',
          image: null,
          packages: [
            { name: 'rclpy', version: '3.3.14' },
            { name: 'numpy', version: '2.1.3' },
            { name: 'opencv-python', version: '4.10.0.84' },
            { name: 'torch', version: '2.4.1+cu121' }
          ],
          detected_on: null,
          provenance: 'detected',
          captured_at: null
        }}
      />
    </Entry>
  )
}

export function DockerImage() {
  return (
    <Entry caption="JETSON ORIN NANO · DEPLOY TARGET">
      <CodeEnvironmentCard
        payload={{
          type: 'docker',
          name: 'ros-humble-runtime',
          path: null,
          interpreter: null,
          image: 'ghcr.io/solus/ari-runtime:cu118',
          packages: [
            { name: 'ros-humble-ros-base', version: '0.10.0' },
            { name: 'cuda-toolkit', version: '11.8' }
          ],
          detected_on: null,
          provenance: 'user',
          captured_at: null
        }}
      />
    </Entry>
  )
}

export function PackagesListed() {
  return (
    <Entry caption="ARI-PERCEPTION · PACKAGE DISCLOSURE">
      <CodeEnvironmentCard
        payload={{
          type: 'python',
          name: 'ari-perception',
          path: null,
          interpreter: null,
          image: null,
          packages: [
            { name: 'rclpy', version: '3.3.14' },
            { name: 'numpy', version: '2.1.3' },
            { name: 'opencv-python', version: '4.10.0.84' },
            { name: 'torch', version: '2.4.1+cu121' }
          ],
          detected_on: null,
          provenance: 'detected',
          captured_at: null
        }}
      />
    </Entry>
  )
}

export function DetectedOnJetson() {
  return (
    <Entry caption="ARI-FIRMWARE · ARDUINO TOOLCHAIN">
      <CodeEnvironmentCard
        payload={{
          type: 'arduino',
          name: 'teensy41',
          path: null,
          interpreter: null,
          image: null,
          packages: [],
          detected_on: { os: 'linux', arch: 'aarch64' },
          provenance: 'sol',
          captured_at: '2026-09-17T09:41:00Z'
        }}
      />
    </Entry>
  )
}

export function Unreadable() {
  return (
    <Entry caption=".SOLUS · CONFIG ENTRY">
      <CodeEnvironmentCard payload={{ kind: 'unknown-document' }} />
    </Entry>
  )
}
