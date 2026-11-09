import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
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

it('marker click opens finding', () => {
  const finding = '0b5f8a3e-8c1d-4c6e-9a1f-2d3e4f5a6b7c'
  const opened = vi.fn()
  const scoped = vi.fn()
  const props = {
    userId: 'u',
    projectId: 'p',
    deviceId: 'd',
    onScope: scoped,
    events: [
      {
        kind: 'threshold_breach',
        device_id: 'd',
        signal: 'angle',
        at: '2026-09-14T12:00:01Z',
        value: null,
        finding_id: finding
      },
      // A plain observer event names no finding: it stays a line, never a control.
      {
        kind: 'change_point',
        device_id: 'd',
        signal: 'angle',
        at: '2026-09-14T12:00:01.5Z',
        value: 1
      }
    ],
    series: {
      signal: 'angle',
      points: [
        { timestamp: '2026-09-14T12:00:00Z', value: 0, unit: 'rad' },
        { timestamp: '2026-09-14T12:00:02Z', value: 1, unit: 'rad' }
      ]
    }
  }
  const { rerender } = render(<SignalWidget {...props} onOpenFinding={opened} />)
  const markers = screen.getAllByRole('button', { name: /^Open finding/ })
  expect(markers).toHaveLength(1)
  expect(markers[0]).toHaveAccessibleName('Open finding: threshold_breach at 2026-09-14T12:00:01Z')
  expect(markers[0].style.left).toContain('50%')
  fireEvent.click(markers[0])
  expect(opened).toHaveBeenCalledExactlyOnceWith(finding)
  expect(scoped).not.toHaveBeenCalled()
  // A host with no findings pane draws the markers as lines only.
  rerender(<SignalWidget {...props} />)
  expect(screen.queryByRole('button', { name: /^Open finding/ })).not.toBeInTheDocument()
  expect(screen.getByLabelText('threshold_breach at 2026-09-14T12:00:01Z')).toBeInTheDocument()
})
