import { cn } from '@/lib/utils'
import { Bot, Database, Languages, LayoutDashboard, Menu, Ticket, X } from 'lucide-react'
import { useState, type ComponentType } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { getHealth } from '@/api'

const mainNav = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true },
  { to: '/tickets', label: 'Tickets', icon: Ticket },
  { to: '/multilingual', label: 'Language coverage', icon: Languages },
  { to: '/agents', label: 'Agents', icon: Bot },
  { to: '/setup', label: 'Setup', icon: Database },
]

const agentNav = [
  { to: '/tickets/new', label: 'Agent 1', subtitle: 'Ticket resolution' },
  { to: '/incidents', label: 'Agent 2', subtitle: 'Anomalies' },
  { to: '/retention', label: 'Agent 3', subtitle: 'Churn risk' },
  { to: '/reports', label: 'Agent 4', subtitle: 'Weekly report' },
]

function MainNavLink({
  to,
  label,
  icon: Icon,
  end,
  onNavigate,
}: {
  to: string
  label: string
  icon: ComponentType<{ className?: string }>
  end?: boolean
  onNavigate: () => void
}) {
  return (
    <NavLink
      to={to}
      end={end}
      onClick={onNavigate}
      className={({ isActive }) =>
        cn(
          'flex items-center gap-3 rounded-lg px-3 py-2.5 text-base font-medium transition',
          isActive
            ? 'bg-brand-50 text-brand-700'
            : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900',
        )
      }
    >
      <Icon className="h-5 w-5 shrink-0" />
      {label}
    </NavLink>
  )
}

function AgentNavLink({
  to,
  label,
  subtitle,
  index,
  onNavigate,
}: {
  to: string
  label: string
  subtitle: string
  index: number
  onNavigate: () => void
}) {
  return (
    <NavLink
      to={to}
      onClick={onNavigate}
      className={({ isActive }) =>
        cn(
          'flex items-start gap-3 rounded-lg border px-3 py-2.5 text-base transition',
          isActive
            ? 'border-violet-400 bg-violet-100 text-violet-950 shadow-sm'
            : 'border-violet-200/80 bg-violet-50/90 text-violet-900 hover:border-violet-300 hover:bg-violet-100',
        )
      }
    >
      <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-violet-600 text-sm font-bold text-white">
        {index}
      </span>
      <span className="min-w-0 leading-tight">
        <span className="block font-semibold">{label}</span>
        <span className="block text-sm font-normal opacity-80">{subtitle}</span>
      </span>
    </NavLink>
  )
}

export function Layout() {
  const [open, setOpen] = useState(false)
  const { data: health } = useQuery({
    queryKey: ['health'],
    queryFn: getHealth,
    refetchInterval: 30000,
  })

  const closeMobile = () => setOpen(false)

  return (
    <div className="flex min-h-screen">
      <aside
        className={cn(
          'fixed inset-y-0 left-0 z-40 w-72 border-r border-slate-200 bg-white transition-transform lg:static lg:translate-x-0',
          open ? 'translate-x-0' : '-translate-x-full',
        )}
      >
        <div className="flex h-16 items-center border-b border-slate-100 px-5">
          <span className="text-xl font-semibold text-slate-900">Support Insight</span>
        </div>
        <nav className="max-h-[calc(100vh-8rem)] space-y-1 overflow-y-auto p-3 pb-24">
          {mainNav.slice(0, 2).map(({ to, label, icon, end }) => (
            <MainNavLink
              key={to}
              to={to}
              label={label}
              icon={icon}
              end={end}
              onNavigate={closeMobile}
            />
          ))}

          <div className="space-y-1.5 py-2">
            {agentNav.map((item, i) => (
              <AgentNavLink
                key={item.to}
                to={item.to}
                label={item.label}
                subtitle={item.subtitle}
                index={i + 1}
                onNavigate={closeMobile}
              />
            ))}
          </div>

          {mainNav.slice(2).map(({ to, label, icon, end }) => (
            <MainNavLink
              key={to}
              to={to}
              label={label}
              icon={icon}
              end={end}
              onNavigate={closeMobile}
            />
          ))}
        </nav>
        <div className="absolute bottom-0 left-0 right-0 border-t border-slate-100 bg-white p-4 text-sm text-slate-500">
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
              'rounded-full px-2.5 py-1 text-sm font-medium',
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
