import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { SignalWidget } from './SignalWidget'
import { convertUnit, displayPoints, unitOptions } from './signalUnits'

beforeEach(() => localStorage.clear())

describe('packet-unit signal display', () => {
  it('keeps one time and value scale across incompatible-unit gaps', () => {
    render(
      <SignalWidget
        userId="u"
        projectId="p"
        deviceId="d"
        series={{
          signal: 'angle',
          points: [
            { timestamp: '2026-09-14T12:00:00Z', value: 0, unit: 'rad' },
            { timestamp: '2026-09-14T12:00:01Z', value: 1, unit: 'rad' },
            { timestamp: '2026-09-14T12:00:02Z', value: 2 },
            { timestamp: '2026-09-14T12:00:03Z', value: 10, unit: 'rad' },
            { timestamp: '2026-09-14T12:00:04Z', value: 20, unit: 'rad' }
          ]
        }}
      />
    )
    const paths = screen.getByRole('img').querySelectorAll('polyline')
    expect(paths[0].getAttribute('points')).toBe('0.0,48.0 60.0,45.6')
    expect(paths[1].getAttribute('points')).toBe('180.0,24.0 240.0,0.0')
  })

  it('converts radians exactly without modifying packets', () => {
    expect(convertUnit(Math.PI, 'rad', 'deg')).toBe(180)
    expect(convertUnit(180, 'deg', 'rad')).toBe(Math.PI)
    expect(unitOptions(null)).toEqual([])
    expect(convertUnit(2, null, 'deg')).toBeNull()
    expect(convertUnit(2, 'A', 'deg')).toBeNull()
  })

  it('rejects conversions that overflow a finite packet value', () => {
    expect(convertUnit(1e308, 'rad', 'deg')).toBeNull()
  })

  it('does not combine unknown or incompatible units in one chart', () => {
    const points = [
      { timestamp: '2026-09-14T12:00:00Z', value: Math.PI, unit: 'rad' },
      { timestamp: '2026-09-14T12:00:01Z', value: 2, unit: null },
      { timestamp: '2026-09-14T12:00:02Z', value: 90, unit: 'deg' }
    ]
    expect(displayPoints(points, 'deg').map((p) => p.value)).toEqual([180, 90])
    expect(points[0].value).toBe(Math.PI)
  })
})

describe('signal widget preferences', () => {
  it('shows packet units and persists an inline name across reconnects within its scope', () => {
    const props = {
      userId: 'u1',
      projectId: 'p1',
      deviceId: 'usb:fixture/1',
      series: {
        signal: 'position',
        points: [{ timestamp: '2026-09-14T12:00:00Z', value: Math.PI, unit: 'rad' }]
      }
    }
    const first = render(<SignalWidget {...props} />)
    fireEvent.change(screen.getByLabelText('Display unit for position'), {
      target: { value: 'deg' }
    })
    expect(screen.getByLabelText('position value')).toHaveTextContent(/180\s*deg/)
    fireEvent.click(screen.getByRole('button', { name: 'Rename position' }))
    fireEvent.change(screen.getByLabelText('Signal name'), { target: { value: 'Wrist angle' } })
    fireEvent.keyDown(screen.getByLabelText('Signal name'), { key: 'Enter' })
    first.unmount()
    const second = render(<SignalWidget {...props} />)
    expect(screen.getByLabelText('Wrist angle value')).toHaveTextContent(/180\s*deg/)
    second.unmount()
    const third = render(<SignalWidget {...props} projectId="p2" />)
    expect(screen.getByLabelText('position value')).toBeInTheDocument()
    expect(screen.queryByText(/Wrist angle/)).not.toBeInTheDocument()
    third.rerender(<SignalWidget {...props} userId="u2" />)
    expect(screen.getByLabelText('position value')).toBeInTheDocument()
    expect(screen.queryByText(/Wrist angle/)).not.toBeInTheDocument()
    expect(screen.getByRole('combobox')).toHaveValue('rad')
  })

  it('does not offer conversion for unitless packets', () => {
    render(
      <SignalWidget
        userId="u"
        projectId="p"
        deviceId="d"
        series={{ signal: 'raw', points: [{ timestamp: '2026-09-14T12:00:00Z', value: 7 }] }}
      />
    )
    expect(screen.getByText('no unit')).toBeInTheDocument()
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
  })
})

it('places evidence markers on time without converting unknown event values', () => {
  render(
    <SignalWidget
      userId="u"
      projectId="p"
      deviceId="d"
      events={[
        {
          kind: 'stream_gap',
          device_id: 'd',
          signal: 'angle',
          at: '2026-09-14T12:00:01Z',
          value: null
        }
      ]}
      series={{
        signal: 'angle',
        points: [
          { timestamp: '2026-09-14T12:00:00Z', value: 0, unit: 'rad' },
          { timestamp: '2026-09-14T12:00:02Z', value: 1, unit: 'rad' }
        ]
      }}
    />
  )
  expect(screen.getByLabelText('stream_gap at 2026-09-14T12:00:01Z')).toHaveAttribute('x1', '120')
  fireEvent.change(screen.getByRole('combobox'), { target: { value: 'deg' } })
  expect(screen.getByLabelText('stream_gap at 2026-09-14T12:00:01Z')).toHaveAttribute('x1', '120')
})
