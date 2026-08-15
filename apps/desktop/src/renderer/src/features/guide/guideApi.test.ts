// SOLUS-TU-09 — typed client for the Guide walkthrough endpoints.
import { describe, it, expect, vi } from 'vitest'
import { listGuides, getGuide, sendFeedback } from './guideApi'
import type { ApiClient } from '../../lib/api/client'

function fakeClient(payload: unknown): ApiClient {
  return {
    request: vi.fn().mockResolvedValue(payload),
    requestPage: vi.fn()
  } as unknown as ApiClient
}

describe('guideApi', () => {
  it('lists guides for a tool + version', async () => {
    const client = fakeClient([
      { id: 'g1', tool: 'kicad', title: 'T', summary: 'S', step_count: 3 }
    ])
    const guides = await listGuides('kicad', '9.0.4', client)
    expect(guides[0].id).toBe('g1')
    expect(client.request).toHaveBeenCalledWith(
      '/toolkb/guides?tool=kicad&version=9.0.4',
      expect.anything()
    )
  })

  it('fetches one resolved guide, passing an abort signal through', async () => {
    const detail = {
      id: 'g1',
      tool: 'kicad',
      title: 'T',
      summary: 'S',
      steps: [
        {
          step_number: 1,
          control_id: 'kicad.eeschema.x',
          note_guide: 'g',
          note_expert: 'e',
          available: true,
          tentative: false,
          label: 'X',
          description: 'does x',
          shortcut: 'L',
          menu_path: null,
          surface: 'keyboard',
          confidence: 0.8
        }
      ]
    }
    const client = fakeClient(detail)
    const controller = new AbortController()
    const guide = await getGuide('g1', '9.0.4', client, controller.signal)
    expect(guide.steps[0].label).toBe('X')
    expect(client.request).toHaveBeenCalledWith(
      '/toolkb/guides/g1?version=9.0.4',
      expect.objectContaining({ signal: controller.signal })
    )
  })

  it('url-encodes the guide id and version', async () => {
    const client = fakeClient({ id: 'a/b', tool: 'kicad', title: '', summary: '', steps: [] })
    await getGuide('a/b', '9.0.4', client)
    expect(client.request).toHaveBeenCalledWith(
      '/toolkb/guides/a%2Fb?version=9.0.4',
      expect.anything()
    )
  })

  it('posts confirm/reject feedback to the entry (TU-08)', async () => {
    const client = fakeClient({ id: 'e1', confidence: 0.27, confirm_count: 0, reject_count: 1 })
    const res = await sendFeedback('e1', 'reject', client)
    expect(res.confidence).toBe(0.27)
    expect(client.request).toHaveBeenCalledWith(
      '/toolkb/entries/e1/feedback',
      expect.objectContaining({ method: 'POST', body: { verdict: 'reject' } })
    )
  })
})
