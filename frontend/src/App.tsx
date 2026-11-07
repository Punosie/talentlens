import { useQuery } from '@tanstack/react-query'
import { Bookmark, CircleHelp, FileUp, House, ListChecks, Moon, Search, Settings, Sun } from 'lucide-react'
import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router'
import { Onboarding } from './components/Onboarding'
import { StatusPill } from './components/StatusPill'
import { Hint } from './components/ui'
import { useIndexStatus } from './hooks/useIndexStatus'
import { api } from './lib/api'
import { cn } from './lib/utils'
import { UploadTray } from './upload/UploadTray'

const NAV = [
  { to: '/', label: 'Home', icon: House, end: true },
  { to: '/search', label: 'Search resumes', icon: Search },
  { to: '/match', label: 'Match to a job', icon: ListChecks },
  { to: '/add', label: 'Add resumes', icon: FileUp },
  { to: '/saved', label: 'Saved lists', icon: Bookmark },
]
const NAV_BOTTOM = [
  { to: '/settings', label: 'Settings', icon: Settings },
  { to: '/help', label: 'Help', icon: CircleHelp },
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
    <Hint content={dark ? 'Light mode' : 'Dark mode'} side="right">
      <button
        type="button"
        onClick={toggle}
        className="flex size-9 items-center justify-center rounded-md text-muted hover:bg-sunken hover:text-text"
        aria-label={dark ? 'Switch to light theme' : 'Switch to dark theme'}
      >
        {dark ? <Sun className="size-4" /> : <Moon className="size-4" />}
      </button>
    </Hint>
  )
}

function NavItem({ to, label, icon: Icon, end }: { to: string; label: string; icon: typeof House; end?: boolean }) {
  return (
    <li>
      <NavLink
        to={to}
        end={end}
        className={({ isActive }) =>
          cn(
            'flex h-10 items-center gap-3 rounded-[8px] px-3 text-[14px] font-medium transition-colors',
            isActive ? 'bg-ink text-on-ink shadow-e1' : 'text-muted hover:bg-sunken hover:text-text',
          )
        }
        title={label}
      >
        <Icon className="size-[18px] shrink-0" />
        <span className="hidden lg:inline">{label}</span>
      </NavLink>
    </li>
  )
}

export default function App() {
  const status = useIndexStatus()
  const location = useLocation()
  const settings = useQuery({ queryKey: ['settings'], queryFn: api.settings })
  const [guide, setGuide] = useState(false)
  const [dismissed, setDismissed] = useState(false)
  const s = settings.data
  const firstRun = !!s && !s.cv_dir
  const needsWelcome = !!s && (!s.cv_dir || (!s.onboarded && s.cv_dir_source !== 'config'))

  useEffect(() => {
    const open = () => setGuide(true)
    window.addEventListener('tl:open-guide', open)
    return () => window.removeEventListener('tl:open-guide', open)
  }, [])
  useEffect(() => {
    document.querySelector('main')?.scrollTo({ top: 0 })
  }, [location.pathname])

  return (
    <div className="flex h-full min-h-0">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:rounded focus:bg-surface focus:px-3 focus:py-2">
        Skip to content
      </a>
      <nav aria-label="Main" className="flex w-16 shrink-0 flex-col border-r border-line bg-surface lg:w-60">
        <div className="flex h-16 items-center gap-2.5 px-4">
          <img src="/favicon.svg" alt="" className="size-8" />
          <span className="hidden text-[17px] font-bold tracking-tight lg:inline">
            Talent<span className="mark">Lens</span>
          </span>
        </div>
        <ul className="flex flex-col gap-1 px-2.5 pt-3">
          {NAV.map((n) => (
            <NavItem key={n.to} {...n} />
          ))}
        </ul>
        <ul className="mt-auto flex flex-col gap-1 px-2.5 pb-2">
          {NAV_BOTTOM.map((n) => (
            <NavItem key={n.to} {...n} />
          ))}
        </ul>
        <div className="flex items-center justify-between border-t border-line p-3">
          <span className="hidden text-[11px] leading-tight text-muted lg:inline">
            Private · runs on
            <br />
            this computer only
          </span>
          <ThemeToggle />
        </div>
      </nav>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-16 shrink-0 items-center justify-end gap-3 border-b border-line bg-paper/90 px-4 backdrop-blur md:px-8">
          <StatusPill status={status} />
        </header>
        <main id="main" className="min-h-0 flex-1 overflow-y-auto">
          <Outlet context={{ status }} />
        </main>
      </div>

      <UploadTray />
      <Onboarding
        open={guide || (needsWelcome && !dismissed)}
        onClose={() => {
          setGuide(false)
          setDismissed(true)
        }}
        status={status}
        firstRun={firstRun}
      />
    </div>
  )
}
