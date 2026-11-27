import { Link } from 'react-router'
import { useApprovalCount } from '@/api/agents'
import { useMyTasks } from '@/api/queries'
import { ScanPanel } from '@/components/ScanPanel'
import { TaskList } from '@/components/TaskList'
import type { User } from '@/api/client'
import { Card, ErrorState, Loading, PageHeader } from '@/components/ui'
import { SCAN_ROLES } from '@/lib/agents'
import { percentOf, toNumber } from '@/lib/format'
import { useAccounts } from './accounts'

function Kpi({ label, value, hint, to }: { label: string; value: string; hint?: string; to?: string }) {
  const body = (
    <>
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-2 text-3xl font-semibold tabular-nums">{value}</div>
      {hint && <div className="mt-1 text-xs text-slate-500">{hint}</div>}
    </>
  )
  return to ? (
    <Link to={to} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm hover:border-brand-300">{body}</Link>
  ) : (
    <Card className="p-5">{body}</Card>
  )
}

export function CommandCentrePage({ user }: { user: User }) {
  const accounts = useAccounts('')
  const tasks = useMyTasks()
  const approvals = useApprovalCount()
  const first = user.full_name.split(' ')[0]

  return (
    <>
      <PageHeader title={`Good day, ${first}`} description={user.role === 'RM' ? 'Your portfolio at a glance.' : 'The whole bank at a glance.'} />
      {accounts.isPending ? (
        <Loading />
      ) : accounts.isError ? (
        <ErrorState error={accounts.error} onRetry={() => void accounts.refetch()} />
      ) : (
        (() => {
          const rows = accounts.data
          // Limits are in different currencies, so the portfolio view uses ratios and counts.
          const utils = rows
            .map((r) => percentOf(r.total_utilized, r.total_limit))
            .filter((v): v is number => v !== null)
          const avgUtil = utils.length ? utils.reduce((a, b) => a + b, 0) / utils.length : 0
          const hot = utils.filter((u) => u >= 75).length
          const kybDue = rows.filter((r) => r.kyb_status !== 'VERIFIED').length
          const alerts = rows.reduce((n, r) => n + toNumber(r.open_ews), 0)
          const markets = new Set(rows.map((r) => r.country)).size
          return (
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <Kpi label="Accounts" value={String(rows.length)} hint={`Across ${markets} GCC ${markets === 1 ? 'market' : 'markets'}`} />
              <Kpi label="Avg utilisation" value={`${avgUtil.toFixed(0)}%`} hint={`${hot} ${hot === 1 ? 'account' : 'accounts'} at 75% or more`} />
              <Kpi label="KYB attention" value={String(kybDue)} hint="Pending renewal or flagged" />
              <Kpi label="Open alerts" value={String(alerts)} hint="Early-warning signals: see the Risk radar" to="/risk" />
            </div>
          )
        })()
      )}
      {(approvals.data?.pending_for_me ?? 0) > 0 && (
        <Link to="/approvals" className="mt-6 flex items-center justify-between gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900 hover:bg-amber-100">
          <span>
            <span className="font-semibold">{approvals.data!.pending_for_me} agent {approvals.data!.pending_for_me === 1 ? 'proposal needs' : 'proposals need'} your approval.</span>{' '}
            Nothing happens until you decide.
          </span>
          <span className="font-medium underline">Review</span>
        </Link>
      )}
      <div className="mt-6 grid gap-4 lg:grid-cols-[3fr_2fr]">
        <Card className="p-5">
          <h2 className="mb-2 text-sm font-semibold">My open tasks</h2>
          {tasks.isPending ? (
            <Loading />
          ) : tasks.isError ? (
            <ErrorState error={tasks.error} onRetry={() => void tasks.refetch()} />
          ) : (
            <TaskList tasks={tasks.data.filter((t) => t.status === 'OPEN')} />
          )}
        </Card>
        {SCAN_ROLES.has(user.role) ? (
          <ScanPanel />
        ) : (
          <Card className="p-5 text-sm text-slate-600">
            <p className="font-medium text-slate-900">Your queue</p>
            <p className="mt-1">
              KYB checks that find a discrepancy come to you for a second-person review in{' '}
              <Link to="/approvals" className="text-brand-700 underline">Approvals</Link>. Every decision is on the{' '}
              <Link to="/audit" className="text-brand-700 underline">audit trail</Link>.
            </p>
          </Card>
        )}
      </div>
    </>
  )
}
