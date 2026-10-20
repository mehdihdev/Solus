// SOLUSDEV-317: the GitHub part of Home's Team & invites view — the GITHUB
// ORGANIZATION card and, under it, GITHUB ORG MEMBERS. One useTeamGithub feeds
// both, so a link made on the card mounts the section at once (and moves focus
// to its heading). The section needs an owner/admin AND a live Organization
// link; a suspended link hides it (the card's warn row says why). HomeScreen
// keys this by team, so a team switch starts clean.
import { useEffect, useRef, useState } from 'react'
import type { TeamMemberApi } from '../../lib/api/resources'
import { liveKeys, useLiveRevisionStore } from '../../store/liveRevisionStore'
import { GitHubOrgCard } from './GitHubOrgCard'
import { GitHubOrgMembersSection } from './GitHubOrgMembersSection'
import { useTeamGithub, type TeamGithub } from './useTeamGithub'

export interface TeamGithubPanelProps {
  teamId: string
  teamName: string
  canManage: boolean
  members: readonly TeamMemberApi[]
  onUpgrade?: () => void
  /** Whether GITHUB ORG MEMBERS is on screen (the members list offers
   *  "Assign GitHub…" only then). */
  onSectionChange?: (shown: boolean) => void
}

export function showsOrgMembers(github: TeamGithub, canManage: boolean): boolean {
  const link = github.installation
  return canManage && link?.account_type === 'Organization' && link.status === 'active'
}

export function TeamGithubPanel({
  teamId,
  teamName,
  canManage,
  members,
  onUpgrade,
  onSectionChange
}: TeamGithubPanelProps): React.JSX.Element {
  const github = useTeamGithub(teamId)
  const shown = showsOrgMembers(github, canManage)
  const focusAfterLink = useFocusAfterLink(github, shown)
  useEffect(() => {
    onSectionChange?.(shown)
  }, [shown, onSectionChange])
  // Unmounted (team switch, personal team): the section is gone too.
  useEffect(() => () => onSectionChange?.(false), [onSectionChange])
  const card: TeamGithub = {
    ...github,
    actions: { ...github.actions, link: focusAfterLink.link }
  }
  return (
    <>
      <GitHubOrgCard
        github={card}
        teamName={teamName}
        canManage={canManage}
        onUpgrade={onUpgrade}
      />
      {shown && (
        <GitHubOrgMembersSection
          key={teamId}
          teamId={teamId}
          members={members}
          inviteMember={github.actions.inviteMember}
          onMembersStale={() =>
            useLiveRevisionStore.getState().bump([liveKeys.teamMembers(teamId)])
          }
          onLinkStale={() => void github.actions.refresh()}
          onUpgrade={onUpgrade}
          autoFocus={focusAfterLink.focus}
        />
      )}
    </>
  )
}

/** True once a link THIS admin started has landed — so focus moves to the new
 *  section's heading, and only then (not when someone else links it live). */
function useFocusAfterLink(
  github: TeamGithub,
  shown: boolean
): { link: () => Promise<void>; focus: boolean } {
  const awaiting = useRef(false)
  const [focus, setFocus] = useState(false)
  // One use: a later remount (suspended → active, live) must not grab focus.
  useEffect(() => {
    if (!shown) setFocus(false)
  }, [shown])
  const linked = github.installation !== null
  useEffect(() => {
    if (!awaiting.current) return
    if (linked) setFocus(true)
    if (linked || github.notice) awaiting.current = false
  }, [linked, github.notice])
  const link = async (): Promise<void> => {
    awaiting.current = true
    await github.actions.link()
  }
  return { link, focus }
}
