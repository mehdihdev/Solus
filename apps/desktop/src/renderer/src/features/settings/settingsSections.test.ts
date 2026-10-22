import { describe, it, expect } from 'vitest'
import { SETTINGS_SECTIONS, SECTION_GROUPS, filterSections } from './settingsSections.constants'
import { LEGAL_LINKS, SOLUS_SITE } from './legalLinks.constants'

describe('SETTINGS_SECTIONS', () => {
  it('has unique ids, each in a known group', () => {
    const ids = SETTINGS_SECTIONS.map((s) => s.id)
    expect(new Set(ids).size).toBe(ids.length)
    for (const s of SETTINGS_SECTIONS) expect(SECTION_GROUPS).toContain(s.group)
  })
})

describe('filterSections', () => {
  const ids = (q: string): string[] => filterSections(SETTINGS_SECTIONS, q).map((s) => s.id)

  it('returns every section for an empty or blank query', () => {
    expect(ids('')).toHaveLength(SETTINGS_SECTIONS.length)
    expect(ids('   ')).toHaveLength(SETTINGS_SECTIONS.length)
  })

  it('matches titles and keywords, case-insensitively', () => {
    expect(ids('APPEAR')).toEqual(['appearance'])
    expect(ids('theme')).toEqual(['appearance'])
    expect(ids('screen')).toEqual(['sol'])
    expect(ids('credits')).toEqual(['plan'])
    expect(ids('onshape')).toEqual(['tools'])
    expect(ids('terms')).toEqual(['about'])
    expect(ids('delete')).toContain('privacy')
  })

  it('returns nothing for a query that matches no section', () => {
    expect(ids('zzz-no-such-setting')).toEqual([])
  })
})

describe('LEGAL_LINKS', () => {
  it('points at solusforge.com over https', () => {
    expect(SOLUS_SITE).toBe('https://solusforge.com')
    expect(LEGAL_LINKS.map((l) => l.href)).toEqual([
      'https://solusforge.com/terms-of-service',
      'https://solusforge.com/privacy-policy',
      'https://solusforge.com/contact'
    ])
  })
})
