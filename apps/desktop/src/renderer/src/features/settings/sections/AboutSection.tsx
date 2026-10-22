// Settings › About & legal (SOLUSDEV-318): Terms of Service, Privacy Policy and
// support on solusforge.com, plus the running app's version. Links are plain
// https with target=_blank — the main window's open handler sends them to the
// system browser (main/externalUrl.ts), so no new IPC is needed for them.
import { useEffect, useState } from 'react'
import { getDesktopAppInfoBridge } from '../../../lib/desktopBridge'
import { Section } from '../settingsUi'
import { LEGAL_LINKS } from '../legalLinks.constants'

function useAppVersion(): string | null {
  const [version, setVersion] = useState<string | null>(null)
  useEffect(() => {
    const bridge = getDesktopAppInfoBridge()
    if (!bridge) return
    let active = true
    bridge.version().then(
      (v) => {
        if (active && typeof v === 'string') setVersion(v)
      },
      () => undefined
    )
    return () => {
      active = false
    }
  }, [])
  return version
}

export function AboutSection(): React.JSX.Element {
  const version = useAppVersion()
  return (
    <Section id="about" title="About & legal">
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
          gap: 8
        }}
      >
        {LEGAL_LINKS.map((link) => (
          <a
            key={link.id}
            href={link.href}
            target="_blank"
            rel="noopener noreferrer"
            className="interactive"
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              padding: '10px 12px',
              border: '1px solid var(--bd)',
              borderRadius: 4,
              background: 'var(--bg)',
              color: 'var(--tx)',
              fontSize: 12.5,
              textDecoration: 'none'
            }}
          >
            {link.label}
            <span aria-hidden="true" style={{ color: 'var(--mut)' }}>
              ↗
            </span>
          </a>
        ))}
      </div>
      {version && (
        <div
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
            color: 'var(--mut)',
            marginTop: 14
          }}
        >
          {`Solus ${version}`}
        </div>
      )}
    </Section>
  )
}
