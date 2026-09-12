// The robot card's own content (SOLUSDEV-250 P4): only the category line remains —
// rename, delete and everything else live in the sidebar.
import type { ReactNode } from 'react'
import type { Entity } from '../../../lib/api/resources'
import type { SolMode } from '../../../store/settingsStore'

export function RobotNodeContent({ entity, mode }: { entity: Entity; mode: SolMode }): ReactNode {
  if (entity.type !== 'robot_category') return null
  return (
    <span>
      {mode === 'Guide'
        ? 'Parts assigned to this category appear inside.'
        : 'Assigned parts inside.'}
    </span>
  )
}
