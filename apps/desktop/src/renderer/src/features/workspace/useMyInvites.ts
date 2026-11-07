// SOLUSDEV-319 (multi-team Home): the invitations waiting for me, shown in the team rail
// (docs/wireflows/home.md "Team rail"). Loaded once per mount; Accept joins and hands the
// new team to the caller (Home switches to it), Decline drops the row. A refusal is named,
// never swallowed: an invite that closed meanwhile leaves the list with a note.
import { useCallback, useEffect, useState } from 'react'
import {
  acceptMyInvite,
  declineMyInvite,
  listMyInvites,
  myInviteRefusal,
  type MyInvite,
  type MyInviteRefusal
} from '../../lib/api/resources.myInvites'

export type MyInvitesStatus = 'loading' | 'ready' | 'unverified' | 'failed'

export interface MyInviteNotice {
  inviteId: string
  refusal: MyInviteRefusal
}

export interface MyInvites {
  status: MyInvitesStatus
  invites: MyInvite[]
  /** The invite whose Accept or Decline is in flight. */
  busyId: string | null
  /** The last refusal, until the next action. */
  notice: MyInviteNotice | null
  accept: (inviteId: string) => Promise<void>
  decline: (inviteId: string) => Promise<void>
}

export function useMyInvites(onJoined: (teamId: string) => void): MyInvites {
  const [status, setStatus] = useState<MyInvitesStatus>('loading')
  const [invites, setInvites] = useState<MyInvite[]>([])
  const [busyId, setBusyId] = useState<string | null>(null)
  const [notice, setNotice] = useState<MyInviteNotice | null>(null)

  useEffect(() => {
    let live = true
    listMyInvites()
      .then((rows) => {
        if (!live) return
        setInvites(rows)
        setStatus('ready')
      })
      .catch((error: unknown) => {
        if (live) setStatus(myInviteRefusal(error) === 'unverified' ? 'unverified' : 'failed')
      })
    return () => {
      live = false
    }
  }, [])

  const run = useCallback(
    async (inviteId: string, action: () => Promise<string | null>): Promise<void> => {
      setBusyId(inviteId)
      setNotice(null)
      try {
        const joined = await action()
        setInvites((rows) => rows.filter((i) => i.id !== inviteId))
        if (joined) onJoined(joined)
      } catch (error) {
        const refusal = myInviteRefusal(error)
        // A closed invite (or one I already joined) can't be acted on again: drop it.
        if (refusal === 'gone' || refusal === 'already_member')
          setInvites((rows) => rows.filter((i) => i.id !== inviteId))
        setNotice({ inviteId, refusal })
      } finally {
        setBusyId(null)
      }
    },
    [onJoined]
  )

  return {
    status,
    invites,
    busyId,
    notice,
    accept: (id) => run(id, async () => (await acceptMyInvite(id)).team_id),
    decline: (id) =>
      run(id, async () => {
        await declineMyInvite(id)
        return null
      })
  }
}
