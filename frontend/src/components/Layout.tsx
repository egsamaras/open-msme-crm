import {
  Building2,
  ClipboardCheck,
  KanbanSquare,
  LayoutDashboard,
  LogOut,
  Radar,
  ScrollText,
  type LucideIcon,
} from 'lucide-react'
import { NavLink, Outlet } from 'react-router'
import type { Role, User } from '@/api/client'
import { useApprovalCount } from '@/api/agents'
import { useAppInfo, useLogout } from '@/auth'
import { PersonaSwitcher } from '@/components/PersonaSwitcher'
import { Badge } from '@/components/ui'
import { cn } from '@/lib/cn'
import { ROLE_LABEL } from '@/lib/format'

type NavItem = { to: string; label: string; icon: LucideIcon; roles?: Role[] }

const NAV: NavItem[] = [
  { to: '/', label: 'Command centre', icon: LayoutDashboard },
  { to: '/accounts', label: 'Accounts', icon: Building2 },
  { to: '/deals', label: 'Pipeline', icon: KanbanSquare },
  { to: '/risk', label: 'Risk radar', icon: Radar },
  { to: '/approvals', label: 'Approvals', icon: ClipboardCheck },
  { to: '/audit', label: 'Audit trail', icon: ScrollText, roles: ['COMPLIANCE', 'ADMIN'] },
]

export function Layout({ user }: { user: User }) {
  const info = useAppInfo()
  const logout = useLogout()
  const approvals = useApprovalCount()
  const waiting = approvals.data?.pending_for_me ?? 0
  // Hiding links is cosmetic; the server enforces every permission.
  const items = NAV.filter((n) => !n.roles || n.roles.includes(user.role))

  return (
    <div className="flex min-h-svh flex-col md:flex-row">
      <aside className="flex shrink-0 flex-col border-b border-slate-200 bg-brand-900 text-slate-100 md:w-60 md:border-b-0">
        <div className="flex items-center gap-2 px-5 py-4">
          <div className="grid size-8 place-items-center rounded-lg bg-brand-500 text-sm font-bold">
            M
          </div>
          <div className="leading-tight">
            <div className="text-sm font-semibold">Open MSME CRM</div>
            <div className="text-xs text-slate-300">Agentic, human-approved</div>
          </div>
        </div>
        <nav aria-label="Main" className="flex gap-1 overflow-x-auto px-3 pb-3 md:flex-col md:pb-0">
          {items.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-3 whitespace-nowrap rounded-lg px-3 py-2 text-sm transition-colors',
                  isActive ? 'bg-white/15 font-medium text-white' : 'text-slate-300 hover:bg-white/10',
                )
              }
            >
              <Icon className="size-4" aria-hidden />
              {label}
              {to === '/approvals' && waiting > 0 && (
                <span className="ml-auto rounded-full bg-amber-400 px-1.5 text-xs font-semibold text-slate-900" aria-label={`${waiting} waiting for you`}>
                  {waiting}
                </span>
              )}
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto hidden px-5 py-4 text-xs text-slate-400 md:block">
          Synthetic data only. Not production banking software.
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex flex-wrap items-center justify-end gap-3 border-b border-slate-200 bg-white px-4 py-3 md:px-8">
          {info.data && (
            <Badge tone={info.data.llm_provider === 'mock' ? 'info' : 'warn'}>
              AI: {info.data.llm_provider === 'mock' ? 'mock mode' : info.data.llm_provider}
            </Badge>
          )}
          {info.data?.dev_persona_switch && <PersonaSwitcher current={user} />}
          <div className="text-right text-sm leading-tight">
            <div className="font-medium">{user.full_name}</div>
            <div className="text-xs text-slate-500">{ROLE_LABEL[user.role]}</div>
          </div>
          <button
            type="button"
            onClick={() => logout.mutate()}
            className="rounded-lg p-2 text-slate-500 hover:bg-slate-100 hover:text-slate-900"
            aria-label="Sign out"
            title="Sign out"
          >
            <LogOut className="size-4" aria-hidden />
          </button>
        </header>
        <main className="flex-1 px-4 py-6 md:px-8">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
