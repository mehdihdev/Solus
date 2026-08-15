// LB-05: the manifest is a valid CTR-01 self-registration — collectManifests
// (the exact validator discovery runs) must accept it as-is.
import { describe, expect, it } from 'vitest'
import { collectManifests } from '@solus/shared-types'
import manifest from './widget.manifest'

describe('livebench widget manifest', () => {
  it('is accepted by the discovery validator', () => {
    const [collected] = collectManifests({
      './livebench/widget.manifest.ts': { default: manifest }
    })
    expect(collected.id).toBe('livebench')
    expect(collected.title).toBe('Live Bench')
  })

  it('declares the runtime and simulation domains with a coarse size hint', () => {
    expect(manifest.domains).toEqual(['simulation', 'runtime'])
    expect(manifest.size.preferred).toBe('wide')
    expect(manifest.size.minimum).toBe('standard')
  })
})
