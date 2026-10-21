// Static plan-card copy: taglines, features, limit rows. Prices are NOT here —
// they come from GET /billing/summary (wireflow §Plan cards, Decision 6).
// Keep in step with ADR-023/024 and the server's PLAN_LIMITS when those change.
import type { PlanType } from '../../lib/api/resources'

export interface PlanCardDef {
  plan: PlanType
  tagline: string
  /** Headline capabilities shown above the limit rows. */
  features: readonly string[]
  /** Ordered [label, limit] pairs; null limit => Unlimited, undefined => Custom. */
  limits: readonly (readonly [string, number | null | undefined])[]
  contactSales?: boolean
}

export const PLAN_CARDS: readonly PlanCardDef[] = [
  {
    plan: 'basic',
    tagline: 'For getting started',
    features: ['All capabilities', 'Starts with 2,500 credits'],
    limits: [
      ['Projects', 3],
      ['Teams', 2],
      ['Integrations', 4]
    ]
  },
  {
    plan: 'pro',
    tagline: 'For full-stack teams',
    features: ['All capabilities', 'Starts with 10,000 credits'],
    limits: [
      ['Projects', null],
      ['Teams', null],
      ['Integrations', null]
    ]
  },
  {
    plan: 'enterprise',
    tagline: 'Custom limits, SSO, and support',
    features: [
      'Per-seat pricing, set per agreement',
      "Billed to your organization's wallet — one subscription covers every seat"
    ],
    limits: [
      ['Projects', undefined],
      ['Teams', undefined],
      ['Integrations', undefined]
    ],
    contactSales: true
  }
]
