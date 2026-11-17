// The robot card's own content (SOLUSDEV-250 P4): nothing on the robot card — rename, delete
// and everything else live in the sidebar. A legacy `robot_category` row (retired by migration
// a32600000001, SOLUSDEV-326; a robot contains its parts directly) keeps its one line.
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
