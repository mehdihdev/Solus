import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { emptySections } from '../graph/useSolusConfig'
import { SolRightPanel } from './SolRightPanel'
import type { SolChat } from './useSolChat'

vi.mock('./CustomInstructionCard', () => ({
  CustomInstructionCard: () => <div>CUSTOM INSTRUCTIONS</div>
}))

const chat: SolChat = {
  items: [],
  status: 'ready',
  streaming: false,
  contextUsed: null,
  creditsExhausted: false,
  activeConversationId: null,
  send: vi.fn(),
  selectConversation: vi.fn(),
  startNewChat: vi.fn(),
  decide: vi.fn(),
  fileArtifact: vi.fn()
}

describe('SolRightPanel', () => {
  it('stacks the design’s sections in order, then the context manifest', () => {
    render(
      <SolRightPanel
        projectId="p1"
        chat={chat}
        solus={{ status: 'ready', entityId: 's', sections: emptySections(), refetch: vi.fn() }}
        pins={[]}
        onUnpin={vi.fn()}
        onUpload={vi.fn()}
        onNavigate={vi.fn()}
      />
    )
    const headings = [
      'CUSTOM INSTRUCTIONS',
      'FILES & IMAGES',
      'NODES IN CONTEXT',
      'ARTIFACTS',
      'CONTEXT IN USE'
    ]
    const positions = headings.map((text) =>
      screen.getByText(text).compareDocumentPosition(document.body)
    )
    expect(positions).toHaveLength(5)
    const order = headings.map((text) => screen.getByText(text))
    for (let i = 1; i < order.length; i += 1) {
      expect(
        order[i - 1].compareDocumentPosition(order[i]) & Node.DOCUMENT_POSITION_FOLLOWING
      ).toBeTruthy()
    }
  })
})
