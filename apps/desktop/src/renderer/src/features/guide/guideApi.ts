// SOLUS-TU-09 — typed client for the Guide walkthrough endpoints.
//
// LANE D owns features/guide/; it consumes the shared api client (importing is
// not editing an @shared path). The resolved-guide shape is local to this
// feature — it is not the raw CTR-05 ToolKnowledge entry but a KB-resolved
// walkthrough step, so it does not belong in @solus/shared-types.
// `ScreenLocator` is the exception to that: it is the same box CTR-05 stores and
// CTR-06 puts on the wire, so it stays ONE type end to end rather than a copy.
import type { ScreenLocator } from '@solus/shared-types'
import { api, type ApiClient } from '../../lib/api/client'

export interface GuideSummary {
  id: string
  tool: string
  title: string
  summary: string
  step_count: number
}

export interface GuideStepView {
  step_number: number
  control_id: string
  entry_id: string | null
  note_guide: string
  note_expert: string
  available: boolean
  tentative: boolean
  stale: boolean
  label: string | null
  description: string | null
  shortcut: string | null
  menu_path: string[] | null
  surface: string | null
  confidence: number | null
  /**
   * Normalised 0..1 box for the control (SOLUS-TU-10 / SOLX-03). The side panel
   * ignores it; the overlay cannot point without it. `null` is the common case —
   * vendor documentation carries no coordinates — and the overlay must fall back
   * rather than guess (features/overlay/overlayDecision.ts).
   */
  locator: ScreenLocator | null
}

export interface GuideDetail {
  id: string
  tool: string
  title: string
  summary: string
  steps: GuideStepView[]
}

export function listGuides(
  tool: string,
  version: string,
  client: ApiClient = api,
  signal?: AbortSignal
): Promise<GuideSummary[]> {
  const qs = new URLSearchParams({ tool, version }).toString()
  return client.request<GuideSummary[]>(`/toolkb/guides?${qs}`, {
    method: 'GET',
    ...(signal ? { signal } : {})
  })
}

export function getGuide(
  guideId: string,
  version: string,
  client: ApiClient = api,
  signal?: AbortSignal
): Promise<GuideDetail> {
  const qs = new URLSearchParams({ version }).toString()
  return client.request<GuideDetail>(`/toolkb/guides/${encodeURIComponent(guideId)}?${qs}`, {
    method: 'GET',
    signal
  })
}

export interface FeedbackResult {
  id: string
  confidence: number
  confirm_count: number
  reject_count: number
}

// TU-08: a user confirms or rejects a guidance step. A reject pulls the shared
// entry's confidence down hard (precision over recall) so a wrongly-learned
// meaning stops being served confidently to everyone. Keyed by the resolved
// step's entry_id (the KB entry UUID).
export function sendFeedback(
  entryId: string,
  verdict: 'confirm' | 'reject',
  client: ApiClient = api
): Promise<FeedbackResult> {
  return client.request<FeedbackResult>(`/toolkb/entries/${encodeURIComponent(entryId)}/feedback`, {
    method: 'POST',
    body: { verdict }
  })
}
