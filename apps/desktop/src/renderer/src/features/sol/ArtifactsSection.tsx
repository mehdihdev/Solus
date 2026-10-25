// ARTIFACTS (design template, SOL page right column): what SOL produced in this chat —
// this session only, since reloaded turns carry no artifact bytes. Right-click offers
// Save to .solus folder (the same idempotent filing the transcript card does), Show in
// chat (there is no honest "open" path for a bearer-protected blob) and Copy contents
// for text media.
import { useState } from 'react'
import { ContextMenu, clampMenuPosition } from '../../components/ui/ContextMenu'
import { Mono } from '../../components/ui/Mono'
import { SOLUS_SECTION_LABELS } from '../../lib/api/resources'
import { useShellStore } from '../workspace/shellStore'
import { artifactExt, isTextArtifact } from './chatArtifacts'
import { fetchArtifactBlob } from './solApi'
import type { ChatArtifact } from './solChatStore'
import type { SolChat } from './useSolChat'

const MENU_BOX = { width: 210, height: 110 }

interface MenuState {
  artifact: ChatArtifact
  x: number
  y: number
}

async function copyContents(projectId: string, artifact: ChatArtifact): Promise<void> {
  try {
    const blob = await fetchArtifactBlob(projectId, artifact.artifactId)
    await navigator.clipboard.writeText(await blob.text())
    useShellStore.getState().setToast({ kind: 'ok', title: 'Copied', body: artifact.title })
  } catch {
    useShellStore
      .getState()
      .setToast({ kind: 'warn', title: 'Could not copy', body: 'The artifact is unavailable.' })
  }
}

export function ArtifactsSection({
  artifacts,
  projectId,
  onFile
}: {
  artifacts: readonly ChatArtifact[]
  projectId: string
  onFile: SolChat['fileArtifact']
}): React.JSX.Element {
  const [menu, setMenu] = useState<MenuState | null>(null)
  const close = (): void => setMenu(null)
  return (
    <section className="sol-side-section" aria-label="Artifacts">
      <div className="sol-side-head">
        <Mono size={10} ls="0.08em">
          ARTIFACTS
        </Mono>
        <span className="sol-side-hint">Right-click to save</span>
      </div>
      {artifacts.length === 0 && (
        <p className="sol-side-empty">
          Artifacts SOL produces in this chat appear here (this session only).
        </p>
      )}
      {artifacts.map((artifact) => (
        <div
          key={artifact.artifactId}
          className="sol-artifact-row interactive"
          role="listitem"
          aria-label={artifact.title}
          onContextMenu={(event) => {
            event.preventDefault()
            setMenu({ artifact, ...clampMenuPosition(event.clientX, event.clientY, MENU_BOX) })
          }}
        >
          <Mono size={10} color="var(--acc)" className="sol-artifact-row-ext">
            {artifactExt(artifact)}
          </Mono>
          <div className="sol-artifact-row-text">
            <span>{artifact.title}</span>
            <Mono size={10}>{artifact.sourceTool ?? artifact.mediaType}</Mono>
          </div>
          {artifact.filedTo && <span className="sol-artifact-row-saved">.solus</span>}
        </div>
      ))}
      {menu && (
        <ContextMenu
          x={menu.x}
          y={menu.y}
          onClose={close}
          items={[
            {
              label: 'Save to .solus folder',
              disabled: menu.artifact.filedTo !== null,
              hint: menu.artifact.filedTo
                ? `Filed to ${SOLUS_SECTION_LABELS[menu.artifact.filedTo]}`
                : undefined,
              onSelect: () => {
                void onFile(menu.artifact.artifactId, 'documentation')
                close()
              }
            },
            {
              label: 'Show in chat',
              onSelect: () => {
                document
                  .getElementById(`sol-artifact-${menu.artifact.artifactId}`)
                  ?.scrollIntoView?.({ block: 'center' })
                close()
              }
            },
            {
              label: 'Copy contents',
              disabled: !isTextArtifact(menu.artifact.mediaType),
              hint: isTextArtifact(menu.artifact.mediaType)
                ? undefined
                : 'Binary artifact — nothing to copy as text',
              onSelect: () => {
                void copyContents(projectId, menu.artifact)
                close()
              }
            }
          ]}
        />
      )}
    </section>
  )
}
