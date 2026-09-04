// SOLUSDEV-235 — the project menu bar under the title row: Solus · View ·
// Robot · Help on the left, the bridge pill / search / bell / sign-out cluster
// on the right. Menu CONTENTS are declarative (`MENUS`) and reuse existing
// navigation and actions only — no item does anything the rail or settings
// cannot already do, so reshaping a menu is a data edit, not a code change.
import { useEffect, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Icons } from '../../components/ui/icons.constants'
import { BridgePill } from './BridgePill'
import { MenuRow } from './ProjectSwitcher'
import { BellButton, SearchBox } from './ShellChrome'
import type { MainScreen } from './shellStore'
import { MENU_BAR_HEIGHT, MENUS, type MenuItem, type MenuSpec } from './menuBar.constants'

export interface MenuBarProps {
  activeScreen: string
  hasProject: boolean
  openCount: number
  /** Linked project id for the bridge pill; null ⇒ pill shows offline. */
  projectId: string | null
  onNavigate: (screen: MainScreen) => void
  onSignOut: () => void
  onBell: () => void
}

export function MenuBar({
  activeScreen,
  hasProject,
  openCount,
  projectId,
  onNavigate,
  onSignOut,
  onBell
}: MenuBarProps): React.JSX.Element {
  const [openId, setOpenId] = useState<string | null>(null)

  useEffect(() => {
    if (!openId) return
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') setOpenId(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [openId])

  const activate = (item: MenuItem): void => {
    setOpenId(null)
    if (item === 'separator') return
    if ('action' in item) onSignOut()
    else if ('screen' in item) onNavigate(item.screen)
  }

  return (
    <div
      className="app-no-drag"
      style={{
        height: MENU_BAR_HEIGHT,
        flexShrink: 0,
        display: 'flex',
        alignItems: 'center',
        gap: 2,
        padding: '0 10px 0 12px',
        borderBottom: '1px solid var(--bd)',
        background: 'var(--bg)',
        position: 'relative',
        zIndex: 40
      }}
    >
      {openId && (
        <div
          data-testid="menu-backdrop"
          style={{ position: 'fixed', inset: 0, zIndex: 60 }}
          onClick={() => setOpenId(null)}
        />
      )}
      {MENUS.map((menu) => (
        <MenuTrigger
          key={menu.id}
          menu={menu}
          brand={menu.id === 'solus'}
          open={openId === menu.id}
          anyOpen={openId !== null}
          hasProject={hasProject}
          activeScreen={activeScreen}
          onOpen={() => setOpenId(menu.id)}
          onToggle={() => setOpenId((cur) => (cur === menu.id ? null : menu.id))}
          onActivate={activate}
        />
      ))}
      <div style={{ flex: 1 }} />
      <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
        <BridgePill projectId={projectId} />
        <SearchBox />
        <BellButton openCount={openCount} onBell={onBell} />
        <Button kind="bare" size="sm" onClick={onSignOut}>
          Sign out
        </Button>
      </div>
    </div>
  )
}

function MenuTrigger({
  menu,
  brand,
  open,
  anyOpen,
  hasProject,
  activeScreen,
  onOpen,
  onToggle,
  onActivate
}: {
  menu: MenuSpec
  brand: boolean
  open: boolean
  anyOpen: boolean
  hasProject: boolean
  activeScreen: string
  onOpen: () => void
  onToggle: () => void
  onActivate: (item: MenuItem) => void
}): React.JSX.Element {
  return (
    <div style={{ position: 'relative', zIndex: open ? 61 : undefined }}>
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={(e) => {
          e.stopPropagation()
          onToggle()
        }}
        // Menubar convention: once one menu is open, hovering a sibling switches to it.
        onMouseEnter={() => anyOpen && !open && onOpen()}
        className="interactive"
        style={{
          background: open ? 'var(--sur2)' : 'transparent',
          border: 'none',
          borderRadius: 4,
          color: brand || open ? 'var(--tx)' : 'var(--mut)',
          cursor: 'pointer',
          fontFamily: 'var(--font-ui)',
          fontSize: 13,
          fontWeight: brand ? 700 : 500,
          padding: '5px 10px'
        }}
      >
        {menu.label}
      </button>
      {open && (
        <div
          role="menu"
          aria-label={menu.label}
          className="popover-in"
          onClick={(e) => e.stopPropagation()}
          style={{
            position: 'absolute',
            left: 0,
            top: '100%',
            marginTop: 6,
            minWidth: 220,
            background: 'var(--sur)',
            border: '1px solid var(--bd)',
            borderRadius: 5,
            boxShadow: '0 14px 44px rgba(0,0,0,0.5)',
            padding: '4px 0'
          }}
        >
          {menu.projectHint && !hasProject && (
            <div style={{ padding: '8px 12px 6px', fontSize: 11.5, color: 'var(--mut)' }}>
              {menu.projectHint}
            </div>
          )}
          {menu.items.map((item, i) => (
            <MenuEntry
              key={item === 'separator' ? `sep-${i}` : item.label}
              item={item}
              hasProject={hasProject}
              activeScreen={activeScreen}
              onActivate={onActivate}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function MenuEntry({
  item,
  hasProject,
  activeScreen,
  onActivate
}: {
  item: MenuItem
  hasProject: boolean
  activeScreen: string
  onActivate: (item: MenuItem) => void
}): React.JSX.Element {
  if (item === 'separator') {
    return <div style={{ borderTop: '1px solid var(--bd)', margin: '4px 0' }} />
  }
  if ('href' in item) {
    return (
      <a
        role="menuitem"
        href={item.href}
        target="_blank"
        rel="noopener noreferrer"
        onClick={() => onActivate(item)}
        className="interactive"
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          padding: '8px 12px',
          fontSize: 12.5,
          color: 'var(--tx)',
          textDecoration: 'none'
        }}
      >
        <span style={{ flex: 1 }}>{item.label}</span>
        <span style={{ color: 'var(--mut)', display: 'inline-flex' }}>
          <Icons.external size={11} />
        </span>
      </a>
    )
  }
  const scoped = 'screen' in item && Boolean(item.projectScoped)
  const disabled = scoped && !hasProject
  const current = 'screen' in item && item.screen === activeScreen
  return (
    <MenuRow
      current={current}
      disabled={disabled}
      title={disabled ? 'Open a project first' : undefined}
      onClick={() => onActivate(item)}
    >
      <span style={{ flex: 1 }}>{item.label}</span>
      {current && (
        <span style={{ color: 'var(--acc)', display: 'inline-flex' }}>
          <Icons.check size={13} />
        </span>
      )}
    </MenuRow>
  )
}
