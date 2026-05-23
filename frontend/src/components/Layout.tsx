import { cn } from '@/lib/utils'
import {
  AlertTriangle,
  Bot,
  Database,
  FileText,
  Heart,
  Languages,
  LayoutDashboard,
  Menu,
  Ticket,
  X,
} from 'lucide-react'
import { useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { getHealth } from '@/api'

const mainNav = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true },
  { to: '/tickets', label: 'Tickets', icon: Ticket, end: false },
] as const

const agentNav = [
  {
    to: '/tickets/new',
    label: 'Agent 1',
    hint: 'Ticket resolution',
    icon: Bot,
    accent: 'border-l-violet-500 bg-violet-50/90 text-violet-900',
    active: 'bg-violet-100 text-violet-900 ring-1 ring-violet-200',
  },
  {
    to: '/incidents',
    label: 'Agent 2',
    hint: 'Anomaly investigation',
    icon: AlertTriangle,
    accent: 'border-l-amber-500 bg-amber-50/80 text-amber-950',
    active: 'bg-amber-100 text-amber-950 ring-1 ring-amber-200',
  },
  {
    to: '/retention',
    label: 'Agent 3',
    hint: 'Customer risk',
    icon: Heart,
    accent: 'border-l-rose-500 bg-rose-50/80 text-rose-950',
    active: 'bg-rose-100 text-rose-950 ring-1 ring-rose-200',
  },
  {
    to: '/reports',
    label: 'Agent 4',
    hint: 'Weekly reports',
    icon: FileText,
    accent: 'border-l-sky-500 bg-sky-50/80 text-sky-950',
    active: 'bg-sky-100 text-sky-950 ring-1 ring-sky-200',
  },
  {
    to: '/multilingual',
    label: 'Language',
    hint: 'Built into Agent 1',
    icon: Languages,
    accent: 'border-l-indigo-500 bg-indigo-50/80 text-indigo-950',
    active: 'bg-indigo-100 text-indigo-950 ring-1 ring-indigo-200',
  },
] as const

const footerNav = [{ to: '/setup', label: 'Setup', icon: Database, end: true }] as const

const navLinkBase =
  'flex items-center gap-3 rounded-lg px-3 py-2.5 text-base font-medium transition'

const mainNavClass = (isActive: boolean) =>
  cn(
    navLinkBase,
    isActive
      ? 'bg-brand-50 text-brand-800'
      : 'text-slate-700 hover:bg-slate-50 hover:text-slate-900',
  )

export function Layout() {
  const [open, setOpen] = useState(false)
  const { data: health } = useQuery({
    queryKey: ['health'],
    queryFn: getHealth,
    refetchInterval: 30000,
  })

  return (
    <div className="flex min-h-screen">
      <aside
        className={cn(
          'fixed inset-y-0 left-0 z-40 flex w-72 flex-col border-r border-slate-200 bg-white transition-transform lg:static lg:translate-x-0',
          open ? 'translate-x-0' : '-translate-x-full',
        )}
      >
        <div className="flex h-16 shrink-0 items-center border-b border-slate-100 px-5">
          <span className="text-xl font-semibold text-slate-900">Support Insight</span>
        </div>

        <nav className="flex-1 space-y-5 overflow-y-auto p-4 pb-28">
          <div className="space-y-1">
            {mainNav.map(({ to, label, icon: Icon, end }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                onClick={() => setOpen(false)}
                className={({ isActive }) => mainNavClass(isActive)}
              >
                <Icon className="h-5 w-5 shrink-0" />
                {label}
              </NavLink>
            ))}
          </div>

          <div className="rounded-xl border border-violet-200/80 bg-gradient-to-b from-violet-50/90 to-slate-50/50 p-2 shadow-sm">
            <div className="mb-2 flex items-center justify-between px-2 pt-1">
              <p className="text-xs font-bold uppercase tracking-wider text-violet-700">
                AI agents
              </p>
              <NavLink
                to="/agents"
                onClick={() => setOpen(false)}
                className={({ isActive }) =>
                  cn(
                    'rounded-md px-2 py-0.5 text-xs font-semibold transition',
                    isActive
                      ? 'bg-violet-600 text-white'
                      : 'text-violet-600 hover:bg-violet-100',
                  )
                }
              >
                Overview
              </NavLink>
            </div>
            <div className="space-y-1">
              {agentNav.map(({ to, label, hint, icon: Icon, accent, active }) => (
                <NavLink
                  key={to + label}
                  to={to}
                  onClick={() => setOpen(false)}
                  className={({ isActive }) =>
                    cn(
                      'flex items-start gap-3 rounded-lg border-l-4 px-3 py-2.5 text-base transition',
                      isActive ? active : cn(accent, 'hover:opacity-90'),
                    )
                  }
                >
                  <Icon className="mt-0.5 h-5 w-5 shrink-0 opacity-80" />
                  <span className="min-w-0">
                    <span className="block font-semibold leading-tight">{label}</span>
                    <span className="block text-sm font-normal opacity-75">{hint}</span>
                  </span>
                </NavLink>
              ))}
            </div>
          </div>

          <div className="space-y-1 border-t border-slate-100 pt-4">
            {footerNav.map(({ to, label, icon: Icon, end }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                onClick={() => setOpen(false)}
                className={({ isActive }) => mainNavClass(isActive)}
              >
                <Icon className="h-5 w-5 shrink-0" />
                {label}
              </NavLink>
            ))}
          </div>
        </nav>

        <div className="shrink-0 border-t border-slate-100 bg-white p-4 text-sm text-slate-500">
          <p>{health?.tickets?.toLocaleString() ?? '—'} tickets</p>
          <p className="truncate">{health?.database ?? 'support.db'}</p>
        </div>
      </aside>

      {open && (
        <button
          type="button"
          className="fixed inset-0 z-30 bg-black/30 lg:hidden"
          onClick={() => setOpen(false)}
          aria-label="Close menu"
        />
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex h-14 items-center gap-4 border-b border-slate-200 bg-white/90 px-4 backdrop-blur lg:px-8">
          <button
            type="button"
            className="rounded-lg p-2 lg:hidden"
            onClick={() => setOpen((v) => !v)}
            aria-label="Menu"
          >
            {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
          <div className="flex-1" />
          <span
            className={cn(
              'rounded-full px-2.5 py-1 text-xs font-medium',
              health?.status === 'ok'
                ? 'bg-emerald-100 text-emerald-800'
                : 'bg-red-100 text-red-800',
            )}
          >
            API {health?.status ?? '…'}
          </span>
        </header>
        <main className="flex-1 p-4 lg:p-8">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
