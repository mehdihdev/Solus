import { describe, expect, it } from 'vitest'
import { loadPose, savePose, poseKey, ZERO_POSE } from './displayPose'

describe('scene display placement', () => {
  it('persists finite per-model poses independently of source revision', () => {
    localStorage.clear()
    const key = poseKey('alice', 'project', 'model')
    const pose = { translation: [1, 2, 3], rotation: [0, 0.4, 0] }
    expect(savePose(key, pose)).toBe(true)
    expect(loadPose(key)).toEqual(pose)
    expect(loadPose(poseKey('bob', 'project', 'model'))).toEqual(ZERO_POSE)
    expect(loadPose(poseKey('alice', 'other', 'model'))).toEqual(ZERO_POSE)
    expect(loadPose(poseKey('alice', 'project', 'another'))).toEqual(ZERO_POSE)
  })
  it('rejects malformed, oversized and nonfinite persisted values', () => {
    for (const raw of [
      'bad',
      '{"translation":[0,0,0],"rotation":[0,0]}',
      'x'.repeat(2049),
      '{"translation":[1e99,0,0],"rotation":[0,0,0]}'
    ]) {
      localStorage.setItem('pose', raw)
      expect(loadPose('pose')).toEqual(ZERO_POSE)
    }
    expect(savePose('pose', { translation: [NaN, 0, 0], rotation: [0, 0, 0] })).toBe(false)
  })
  it('does not persist a signed-out user preference', () => {
    expect(poseKey(null, 'p', 'm')).toBeNull()
    expect(savePose(null, ZERO_POSE)).toBe(false)
    expect(loadPose(null)).toEqual(ZERO_POSE)
  })
})
