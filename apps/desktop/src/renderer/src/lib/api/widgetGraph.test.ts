import { expect, it, vi } from 'vitest'
import { reconcileWidgetGraph } from './widgetGraph'
import type { ApiClient } from './client'

it('reconciles through the existing scoped POST with cancellation', async () => {
  const request = vi.fn().mockResolvedValue({})
  const client = { request } as unknown as ApiClient
  const controller = new AbortController()
  await reconcileWidgetGraph('p/1', controller.signal, client)
  expect(request).toHaveBeenCalledWith('/projects/p%2F1/widgets/graph/reconcile', {
    method: 'POST',
    signal: controller.signal
  })
})
