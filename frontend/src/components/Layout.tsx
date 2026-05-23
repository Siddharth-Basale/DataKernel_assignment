import { cn } from '@/lib/utils'
import {
  AlertTriangle,
  Bot,
  Database,
  Heart,
  LayoutDashboard,
  Menu,
  Ticket,
  X,
} from 'lucide-react'
import { useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { getHealth } from '@/api'

const nav = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/tickets', label: 'Tickets', icon: Ticket },
  { to: '/tickets/new', label: 'New ticket', icon: Ticket },
  { to: '/incidents', label: 'Incidents', icon: AlertTriangle },
  { to: '/retention', label: 'Retention', icon: Heart },
  { to: '/agents', label: 'Agents', icon: Bot },
  { to: '/setup', label: 'Setup', icon: Database },
]

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
          'fixed inset-y-0 left-0 z-40 w-64 border-r border-slate-200 bg-white transition-transform lg:static lg:translate-x-0',
          open ? 'translate-x-0' : '-translate-x-full',
        )}
      >
        <div className="flex h-16 items-center border-b border-slate-100 px-5">
          <span className="text-lg font-semibold text-slate-900">Support Insight</span>
        </div>
        <nav className="space-y-1 p-3">
          {nav.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              onClick={() => setOpen(false)}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition',
                  isActive
                    ? 'bg-brand-50 text-brand-700'
                    : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900',
                )
              }
            >
              <Icon className="h-4 w-4" />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="absolute bottom-0 left-0 right-0 border-t border-slate-100 p-4 text-xs text-slate-500">
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
