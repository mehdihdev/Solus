// One project's activity, in full (SOLUSDEV-242). The card previews a window
// of the team feed; this dialog asks the server for the project's own rows.
import { ActivityModal } from '../team/ActivityModal'
import { useProjectActivity } from './useProjectActivity'

export interface ProjectActivityModalProps {
  teamId: string
  project: { id: string; name: string }
  onClose: () => void
}

export function ProjectActivityModal({
  teamId,
  project,
  onClose
}: ProjectActivityModalProps): React.JSX.Element {
  const feed = useProjectActivity(teamId, project.id)
  return (
    <ActivityModal
      title={`${project.name} — activity`}
      activity={feed.activity}
      total={feed.total}
      hasMore={feed.hasMore}
      onLoadMore={feed.loadMore}
      onClose={onClose}
    />
  )
}
