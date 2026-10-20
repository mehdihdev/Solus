// SOLUSDEV-317: "Assign GitHub…" on a member row (MembersPanel) asks the GITHUB
// ORG MEMBERS section to scroll into view, show "Unassigned teammates" and open
// that teammate's picker — one picker implementation, two entry points. `seq`
// makes a repeat click on the same teammate a new request.
import { create } from 'zustand'

export interface GithubAssignRequest {
  teamId: string
  userId: string
  seq: number
}

interface GithubAssignFocusState {
  request: GithubAssignRequest | null
  requestAssign: (teamId: string, userId: string) => void
  clear: () => void
}

let nextSeq = 0

export const useGithubAssignFocusStore = create<GithubAssignFocusState>((set) => ({
  request: null,
  requestAssign: (teamId, userId) => set({ request: { teamId, userId, seq: ++nextSeq } }),
  clear: () => set({ request: null })
}))
