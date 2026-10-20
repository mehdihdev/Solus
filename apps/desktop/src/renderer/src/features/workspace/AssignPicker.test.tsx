// SOLUSDEV-317: the one picker both sides of the assignment use.
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AssignPicker } from './AssignPicker'
import type { PickerOption } from './githubOrgMembersView'

const opt = (id: string, disabled = false): PickerOption => ({
  id,
  label: `Name ${id}`,
  detail: `${id}@team.dev`,
  disabled
})

function setup(options: PickerOption[], extra: Partial<Parameters<typeof AssignPicker>[0]> = {}) {
  const onPick = vi.fn()
  const utils = render(
    <AssignPicker
      label="Assign"
      listLabel="Teammate for @octo"
      options={options}
      emptyText="Nobody left."
      onPick={onPick}
      {...extra}
    />
  )
  return { onPick, ...utils }
}

describe('AssignPicker', () => {
  it('opens a labelled listbox and focuses the first enabled option', async () => {
    setup([opt('a', true), opt('b')])
    const trigger = screen.getByRole('button', { name: 'Assign' })
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
    await userEvent.click(trigger)
    expect(trigger).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('listbox', { name: 'Teammate for @octo' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: /Name b/ })).toHaveFocus()
    expect(screen.getByRole('option', { name: /Name a/ })).toHaveAttribute('aria-disabled', 'true')
  })

  it('moves focus with the arrows (roving), skipping disabled, and picks with Enter', async () => {
    const { onPick } = setup([opt('a'), opt('b', true), opt('c')])
    await userEvent.click(screen.getByRole('button', { name: 'Assign' }))
    await userEvent.keyboard('{ArrowDown}')
    expect(screen.getByRole('option', { name: /Name c/ })).toHaveFocus()
    expect(screen.getByRole('option', { name: /Name a/ })).toHaveAttribute('tabindex', '-1')
    await userEvent.keyboard('{ArrowUp}{End}{Home}{Enter}')
    expect(onPick).toHaveBeenCalledWith('a')
    expect(screen.queryByRole('listbox')).toBeNull()
  })

  it('never picks a disabled option by click', async () => {
    const { onPick } = setup([opt('a', true)])
    await userEvent.click(screen.getByRole('button', { name: 'Assign' }))
    await userEvent.click(screen.getByRole('option', { name: /Name a/ }))
    expect(onPick).not.toHaveBeenCalled()
  })

  it('Escape closes and returns focus to the trigger; a click outside closes', async () => {
    setup([opt('a')])
    const trigger = screen.getByRole('button', { name: 'Assign' })
    await userEvent.click(trigger)
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('listbox')).toBeNull()
    expect(trigger).toHaveFocus()
    await userEvent.click(trigger)
    await userEvent.click(document.body)
    expect(screen.queryByRole('listbox')).toBeNull()
  })

  it('adds a search filter past 8 options', async () => {
    const many = Array.from({ length: 9 }, (_, i) => opt(`p${i}`))
    setup(many)
    await userEvent.click(screen.getByRole('button', { name: 'Assign' }))
    const search = screen.getByRole('searchbox', { name: /search/i })
    expect(search).toHaveFocus()
    await userEvent.type(search, 'p3@')
    expect(screen.getAllByRole('option')).toHaveLength(1)
    await userEvent.keyboard('{ArrowDown}')
    expect(screen.getByRole('option', { name: /Name p3/ })).toHaveFocus()
  })

  it('has no search for 8 or fewer, and says so when nothing is left', async () => {
    setup([])
    await userEvent.click(screen.getByRole('button', { name: 'Assign' }))
    expect(screen.queryByRole('searchbox')).toBeNull()
    expect(screen.getByText('Nobody left.')).toBeInTheDocument()
  })
})

describe('AssignPicker — control', () => {
  it('opens itself when openRequest changes', () => {
    const { rerender, onPick } = setup([opt('a')], { openRequest: 0 })
    expect(screen.queryByRole('listbox')).toBeNull()
    rerender(
      <AssignPicker
        label="Assign"
        listLabel="L"
        options={[opt('a')]}
        emptyText="-"
        onPick={onPick}
        openRequest={1}
      />
    )
    expect(screen.getByRole('listbox')).toBeInTheDocument()
  })

  it('is inert while disabled', () => {
    setup([opt('a')], { disabled: true })
    expect(screen.getByRole('button', { name: 'Assign' })).toBeDisabled()
  })
})

describe('AssignPicker — review regressions', () => {
  it('Tab out closes it', async () => {
    render(
      <>
        <AssignPicker
          label="Assign"
          listLabel="L"
          options={[opt('a')]}
          emptyText="-"
          onPick={vi.fn()}
        />
        <button>after</button>
      </>
    )
    await userEvent.click(screen.getByRole('button', { name: 'Assign' }))
    await userEvent.tab()
    expect(screen.queryByRole('listbox')).toBeNull()
  })

  it('with nothing pickable, Escape still closes and no option claims selection', async () => {
    setup([opt('a', true)])
    await userEvent.click(screen.getByRole('button', { name: 'Assign' }))
    expect(screen.getByRole('option')).toHaveAttribute('aria-selected', 'false')
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('listbox')).toBeNull()
  })
})
