import { act, renderHook } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { useMentionPicker } from './useMentionPicker'

vi.mock('./useMentionSearch', () => ({ useMentionSearch: () => [] }))

it('does not carry selected ids into a different project or back again', () => {
  const setInput = vi.fn()
  const { result, rerender } = renderHook(
    ({ project, input }) => useMentionPicker(project, input, setInput),
    { initialProps: { project: 'p1', input: '@index' } }
  )
  const el = document.createElement('input')
  el.value = '@index'
  act(() => result.current.onInput(el))
  act(() =>
    result.current.choose({
      id: 'old',
      name: 'index.ts',
      type: 'code_file',
      domain: 'code',
      source_key: 'src/index.ts'
    })
  )
  rerender({ project: 'p1', input: '@index.ts ' })
  expect(result.current.mentionIds).toEqual(['old'])
  rerender({ project: 'p2', input: '@index.ts ' })
  expect(result.current.mentionIds).toEqual([])
  rerender({ project: 'p1', input: '@index.ts ' })
  expect(result.current.mentionIds).toEqual([])
})
