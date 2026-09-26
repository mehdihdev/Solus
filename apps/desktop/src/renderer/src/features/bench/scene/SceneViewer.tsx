import { useEffect, useRef, useState } from 'react'
import {
  AmbientLight,
  Box3,
  DirectionalLight,
  GridHelper,
  PerspectiveCamera,
  Scene,
  Vector3,
  WebGLRenderer
} from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { applyJoints, buildModel, disposeModel } from './kinematics'
import { ZERO_POSE, type DisplayPose } from './displayPose'
import type { SceneModel } from './types'

interface Props {
  compact?: boolean
  models: SceneModel[]
  poses: Record<string, DisplayPose>
  values: Record<string, Record<string, number>>
}
export function SceneViewer(props: Props): React.JSX.Element {
  const host = useRef<HTMLDivElement>(null)
  const latest = useRef(props)
  const [unavailable, setUnavailable] = useState(false)
  useEffect(() => {
    latest.current = props
  }, [props])
  useEffect(() => {
    const element = host.current
    if (!element) return
    let renderer: WebGLRenderer
    try {
      renderer = new WebGLRenderer({ antialias: true, alpha: true })
    } catch {
      queueMicrotask(() => setUnavailable(true))
      return
    }
    const scene = new Scene(),
      camera = new PerspectiveCamera(45, 1, 0.001, 10000)
    camera.up.set(0, 0, 1)
    camera.position.set(1, -1, 0.8)
    const controls = new OrbitControls(camera, renderer.domElement)
    const light = new DirectionalLight(0xffffff, 2)
    light.position.set(2, -2, 4)
    scene.add(new AmbientLight(0xffffff, 1.5), light)
    const grid = new GridHelper(4, 20, 0x64748b, 0x334155)
    grid.rotation.x = Math.PI / 2
    if (!props.compact) scene.add(grid)
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
    element.appendChild(renderer.domElement)
    renderer.domElement.setAttribute('aria-label', 'Robot kinematic scene')
    const built = props.models.map((model) => ({
      model,
      scene: buildModel(model.model, props.compact && model.model.joints.length > 0)
    }))
    for (const item of built) {
      const pose = latest.current.poses[item.model.id] ?? ZERO_POSE
      item.scene.root.position.fromArray(pose.translation)
      item.scene.root.rotation.set(pose.rotation[0], pose.rotation[1], pose.rotation[2], 'ZYX')
      scene.add(item.scene.root)
    }
    const labels = built.flatMap((item) =>
      item.model.bindings.flatMap((binding) => {
        const joint = item.scene.joints.get(binding.joint)
        if (!joint) return []
        const label = document.createElement('span')
        label.className = 'bench-joint-chip'
        label.textContent = binding.signal
        label.title = `${item.model.name} · ${binding.joint}`
        element.appendChild(label)
        return [{ joint, label }]
      })
    )
    if (built.length) {
      const box = new Box3()
      built.forEach((item) => box.expandByObject(item.scene.root))
      if (!box.isEmpty()) {
        const center = box.getCenter(new Vector3()),
          size = Math.max(box.getSize(new Vector3()).length(), 0.3)
        controls.target.copy(center)
        camera.position.copy(center).add(new Vector3(size, -size, size * 0.8))
      }
    }
    let frame = 0,
      disposed = false
    const resize = (): void => {
      const width = Math.max(element.clientWidth, 1),
        height = Math.max(element.clientHeight, 300)
      renderer.setSize(width, height)
      camera.aspect = width / height
      camera.updateProjectionMatrix()
    }
    resize()
    const observer = new ResizeObserver(resize)
    observer.observe(element)
    const render = (): void => {
      if (disposed) return
      for (const item of built) {
        const pose = latest.current.poses[item.model.id] ?? ZERO_POSE
        item.scene.root.position.fromArray(pose.translation)
        item.scene.root.rotation.set(pose.rotation[0], pose.rotation[1], pose.rotation[2], 'ZYX')
        applyJoints(item.scene, item.model.model, latest.current.values[item.model.id] ?? {})
      }
      controls.update()
      scene.updateMatrixWorld(true)
      for (const { joint, label } of labels) {
        const point = joint.getWorldPosition(new Vector3()).project(camera)
        label.style.display = point.z < -1 || point.z > 1 ? 'none' : 'block'
        label.style.left = `${((point.x + 1) * element.clientWidth) / 2 + 8}px`
        label.style.top = `${((1 - point.y) * element.clientHeight) / 2}px`
      }
      renderer.render(scene, camera)
      frame = requestAnimationFrame(render)
    }
    render()
    return () => {
      disposed = true
      cancelAnimationFrame(frame)
      observer.disconnect()
      controls.dispose()
      labels.forEach(({ label }) => label.remove())
      built.forEach((item) => disposeModel(item.scene))
      grid.geometry.dispose()
      ;(Array.isArray(grid.material) ? grid.material : [grid.material]).forEach((material) =>
        material.dispose()
      )
      renderer.dispose()
      renderer.forceContextLoss()
      renderer.domElement.remove()
    }
  }, [props.models, props.compact])
  return (
    <div
      style={{
        minHeight: props.compact ? 240 : 320,
        height: props.compact ? 260 : 420,
        position: 'relative'
      }}
    >
      <div
        ref={host}
        style={{ width: '100%', height: '100%', position: 'relative', overflow: 'hidden' }}
      />
      {unavailable && (
        <p role="status">
          3D rendering is unavailable on this graphics device. Imported models and mappings remain
          available below.
        </p>
      )}
    </div>
  )
}
