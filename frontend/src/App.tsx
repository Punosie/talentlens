import { Bookmark, FileUp, ListChecks, Moon, Search, Sun } from 'lucide-react'
import { useState } from 'react'
import { NavLink, Outlet } from 'react-router'
import { IndexStatusBar } from './components/IndexStatusBar'
import { useIndexStatus } from './hooks/useIndexStatus'
import { cn } from './lib/utils'

const NAV = [
  { to: '/', label: 'Library', icon: Search, end: true },
  { to: '/upload', label: 'Add resumes', icon: FileUp },
  { to: '/shortlist', label: 'Shortlist', icon: ListChecks },
  { to: '/saved', label: 'Saved', icon: Bookmark },
]

function ThemeToggle() {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains('dark'))
  const toggle = () => {
    const next = !dark
    document.documentElement.classList.toggle('dark', next)
    try {
      localStorage.setItem('tl-theme', next ? 'dark' : 'light')
    } catch {
      /* private mode */
    }
    setDark(next)
  }
  return (
    <button
      type="button"
      onClick={toggle}
      className="flex size-9 items-center justify-center rounded-md text-muted hover:bg-sunken hover:text-text"
      aria-label={dark ? 'Switch to light theme' : 'Switch to dark theme'}
    >
      {dark ? <Sun className="size-4" /> : <Moon className="size-4" />}
    </button>
  )
}

function Wordmark() {
  return (
    <span className="flex items-center gap-2 text-[17px] font-bold tracking-tight">
      <img src="/favicon.svg" alt="" className="size-7" />
      <span>
        Talent<span className="mark">Lens</span>
      </span>
    </span>
  )
}

export default function App() {
  const status = useIndexStatus()
  return (
    <div className="flex h-full min-h-0">
      <nav
        aria-label="Main"
        className="flex w-16 shrink-0 flex-col border-r border-line bg-surface lg:w-56"
      >
        <div className="flex h-16 items-center px-4">
          <span className="lg:hidden">
            <img src="/favicon.svg" alt="TalentLens" className="size-8" />
          </span>
          <span className="hidden lg:block">
            <Wordmark />
          </span>
        </div>
        <ul className="flex flex-col gap-1 px-2 pt-2">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <li key={to}>
              <NavLink
                to={to}
                end={end}
                className={({ isActive }) =>
                  cn(
                    'flex h-10 items-center gap-3 rounded-md px-3 text-sm font-medium',
                    isActive ? 'bg-ink text-on-ink' : 'text-muted hover:bg-sunken hover:text-text',
                  )
                }
                title={label}
              >
                <Icon className="size-[18px] shrink-0" />
                <span className="hidden lg:inline">{label}</span>
              </NavLink>
            </li>
          ))}
        </ul>
        <div className="mt-auto flex items-center justify-between p-3">
          <span className="hidden text-[11px] text-muted lg:inline">Runs on this computer only</span>
          <ThemeToggle />
        </div>
      </nav>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-16 shrink-0 items-center justify-end gap-4 border-b border-line bg-paper/90 px-4 backdrop-blur md:px-6">
          <IndexStatusBar status={status} />
        </header>
        <main className="min-h-0 flex-1 overflow-y-auto">
          <Outlet context={{ status }} />
        </main>
      </div>
    </div>
  )
}
