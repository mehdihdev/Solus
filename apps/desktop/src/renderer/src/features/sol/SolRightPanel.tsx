// The SOL page's right column (design template): CUSTOM INSTRUCTIONS · FILES & IMAGES ·
// NODES IN CONTEXT · ARTIFACTS, then the last turn's honest context manifest.
import type { SolusState } from '../graph/useSolusConfig'
import type { MainScreen } from '../workspace/shellStore'
import { ArtifactsSection } from './ArtifactsSection'
import { collectArtifacts } from './chatArtifacts'
import { ContextPanel } from './ContextPanel'
import { CustomInstructionCard } from './CustomInstructionCard'
import { FilesSection } from './FilesSection'
import type { PinnedNode } from './pinnedContextStore'
import { PinnedNodesSection } from './PinnedNodesSection'
import type { SolChat } from './useSolChat'

export function SolRightPanel({
  projectId,
  chat,
  solus,
  pins,
  onUnpin,
  onUpload,
  onNavigate
}: {
  projectId: string
  chat: SolChat
  solus: SolusState
  pins: readonly PinnedNode[]
  onUnpin: (entityId: string) => void
  onUpload: (file: File) => void
  onNavigate: (screen: MainScreen) => void
}): React.JSX.Element {
  return (
    <aside className="sol-right" aria-label="Chat context">
      <CustomInstructionCard />
      <FilesSection solus={solus} onUpload={onUpload} />
      <PinnedNodesSection
        pins={pins}
        onUnpin={onUnpin}
        onFromGraph={() => onNavigate('workspace')}
      />
      <ArtifactsSection
        artifacts={collectArtifacts(chat.items)}
        projectId={projectId}
        onFile={chat.fileArtifact}
      />
      <ContextPanel contextUsed={chat.contextUsed} />
    </aside>
  )
}
