// Shared page chrome: sticky top nav + page container, with a slide-in sheet
// on mobile.

import { useEffect, useState } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import { useTheme } from '../lib/theme'
import { Icon } from './fields'

const NAV_PAGES = [
  { path: '/images', label: 'Images', icon: 'image' },
  { path: '/displays', label: 'Displays', icon: 'cast' },
  { path: '/jobs', label: 'Jobs', icon: 'sync' },
  { path: '/genai', label: 'GenAI', icon: 'auto_awesome' },
  { path: '/settings', label: 'Settings', icon: 'settings' },
]

// Deep-linked detail routes highlight their parent section in the nav.
const SECTION_BY_PREFIX: Array<[string, string]> = [
  ['/images', '/images'],
  ['/displays', '/displays'],
  ['/grids', '/displays'],
  ['/jobs', '/jobs'],
  ['/sync-jobs', '/jobs'],
  ['/gemini-jobs', '/jobs'],
  ['/genai', '/genai'],
  ['/generate', '/genai'],
  ['/prompts', '/genai'],
  ['/settings', '/settings'],
]

export function Layout() {
  const location = useLocation()
  const [sheetOpen, setSheetOpen] = useState(false)
  const [theme, toggleTheme] = useTheme()
  const activeSection = SECTION_BY_PREFIX.find(([prefix]) => location.pathname.startsWith(prefix))?.[1]

  useEffect(() => setSheetOpen(false), [location.pathname])

  return (
    <>
      <header className="ink-nav">
        <Link to="/" className="ink-nav-brand">
          <span className="ink-nav-brand-dot" />
          <span>Inky</span>
          <span className="ink-muted" style={{ fontWeight: 400 }}>
            / image display
          </span>
        </Link>
        <div className="flex-1" />
        <nav className="ink-nav-links">
          {NAV_PAGES.map((page) => (
            <NavLink
              key={page.path}
              to={page.path}
              className={`ink-nav-link ${page.path === activeSection ? 'is-active' : ''}`}
            >
              {page.label}
            </NavLink>
          ))}
        </nav>
        <button
          className="ink-btn ink-btn-flat ink-btn-icon"
          aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
          title={theme === 'dark' ? 'Light mode' : 'Dark mode'}
          onClick={toggleTheme}
        >
          <Icon name={theme === 'dark' ? 'light_mode' : 'dark_mode'} />
        </button>
        <button
          className="ink-btn ink-btn-ghost ink-btn-icon ink-nav-mobile-toggle"
          aria-label="Open menu"
          onClick={() => setSheetOpen(true)}
        >
          <Icon name="menu" />
        </button>
      </header>

      {sheetOpen && (
        <>
          <div className="ink-sheet-backdrop" onClick={() => setSheetOpen(false)} />
          <div className="ink-sheet">
            <div className="row justify-between items-center" style={{ padding: '0 8px 8px' }}>
              <span className="ink-eyebrow">Menu</span>
              <button className="ink-btn ink-btn-icon ink-btn-flat" aria-label="Close menu" onClick={() => setSheetOpen(false)}>
                <Icon name="close" />
              </button>
            </div>
            {NAV_PAGES.map((page) => (
              <NavLink
                key={page.path}
                to={page.path}
                className={`ink-nav-link ${page.path === activeSection ? 'is-active' : ''}`}
              >
                <Icon name={page.icon} />
                {page.label}
              </NavLink>
            ))}
          </div>
        </>
      )}

      <main className="ink-page">
        <Outlet />
      </main>
    </>
  )
}
