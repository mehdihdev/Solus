import { expect, it } from 'vitest'
import { parsePointCloud } from './sensorMedia'

it('accepts measured metre triples and preserves their coordinates', () => {
  expect(parsePointCloud('{"schema_version":1,"unit":"m","points":[[1,2,3],[-4,0,2]]}')).toEqual([
    [1, 2, 3],
    [-4, 0, 2]
  ])
})
it.each([
  '{"schema_version":1,"unit":"deg","points":[[1,2,3]]}',
  '{"schema_version":1,"unit":"m","points":[[1,2]]}',
  '{"schema_version":1,"unit":"m","points":[[1,2,1e400]]}',
  '{"schema_version":1,"unit":"m","points":[],"script":"bad"}',
  JSON.stringify({
    schema_version: 1,
    unit: 'm',
    points: Array.from({ length: 10001 }, () => [1, 2, 3])
  })
])('rejects invalid or oversized point clouds', (text) => {
  expect(() => parsePointCloud(text)).toThrow()
})
