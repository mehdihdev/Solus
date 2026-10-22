// Settings › About & legal (SOLUSDEV-318). The public site's legal and contact
// pages. Opened as plain https links: the main window's open handler sends
// https to the system browser (main/externalUrl.ts).
export const SOLUS_SITE = 'https://solusforge.com'

export interface LegalLink {
  readonly id: 'terms' | 'privacy' | 'contact'
  readonly label: string
  readonly href: string
}

export const LEGAL_LINKS: readonly LegalLink[] = [
  { id: 'terms', label: 'Terms of Service', href: `${SOLUS_SITE}/terms-of-service` },
  { id: 'privacy', label: 'Privacy Policy', href: `${SOLUS_SITE}/privacy-policy` },
  { id: 'contact', label: 'Contact support', href: `${SOLUS_SITE}/contact` }
]

export const PRIVACY_POLICY_URL = `${SOLUS_SITE}/privacy-policy`
