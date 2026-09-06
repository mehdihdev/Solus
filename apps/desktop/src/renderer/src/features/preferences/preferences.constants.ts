// SOLUSDEV-244 / HOME H3: what each section of ~/.solus/preferences.json is
// for, in the words the card shows. Order matches PREFERENCE_SECTIONS.
import type { PreferenceSection } from '@solus/shared-types'

export interface SectionCopy {
  label: string
  placeholder: string
}

export const SECTION_COPY: Readonly<Record<PreferenceSection, SectionCopy>> = {
  codeStyle: {
    label: 'Code style',
    placeholder: 'C++17 on firmware, no dynamic allocation in ISRs; Python typed and ruff-clean.'
  },
  mechanical: {
    label: 'Mechanical',
    placeholder: 'Metric fasteners only. 6061-T6 unless stated. Heat-set inserts in printed parts.'
  },
  electrical: {
    label: 'Electrical',
    placeholder: 'Prefer 0.1 mm clearance minimum on all boards. JST-GH for signal, XT30 for power.'
  },
  documentation: {
    label: 'Documentation',
    placeholder: 'Every board ships with a one-page bring-up note. Diagrams over prose.'
  },
  unitsStandards: {
    label: 'Units and standards',
    placeholder: 'SI units. ISO 2768-m general tolerances. REP 103 frames in ROS.'
  }
}

export const FREE_TEXT_COPY: SectionCopy = {
  label: 'Anything else',
  placeholder: 'How you like to work, what SOL should assume, what it should never suggest.'
}
