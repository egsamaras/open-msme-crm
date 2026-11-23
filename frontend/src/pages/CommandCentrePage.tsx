import { Link } from 'react-router'
import { useApprovalCount } from '@/api/agents'
import { useMyTasks } from '@/api/queries'
import { TaskList } from '@/components/TaskList'
import type { User } from '@/api/client'
import { Card, ErrorState, Loading, PageHeader } from '@/components/ui'
import { percentOf, toNumber } from '@/lib/format'
import { useAccounts } from './accounts'

function Kpi({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <Card className="p-5">
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-2 text-3xl font-semibold tabular-nums">{value}</div>
      {hint && <div className="mt-1 text-xs text-slate-500">{hint}</div>}
    </Card>
  )
}

export function CommandCentrePage({ user }: { user: User }) {
  const accounts = useAccounts('')
  const tasks = useMyTasks()
  const approvals = useApprovalCount()
  const first = user.full_name.split(' ')[0]

  return (
    <>
      <PageHeader title={`Good day, ${first}`} description="Your portfolio at a glance." />
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
          return (
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <Kpi label="Accounts" value={String(rows.length)} hint="Across 6 GCC markets" />
              <Kpi label="Avg utilisation" value={`${avgUtil.toFixed(0)}%`} hint={`${hot} ${hot === 1 ? 'account' : 'accounts'} at 75% or more`} />
              <Kpi label="KYB attention" value={String(kybDue)} hint="Pending renewal or flagged" />
              <Kpi label="Open alerts" value={String(alerts)} hint="Run a portfolio scan in Phase 4" />
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
        <Card className="p-5 text-sm text-slate-600">
          <p className="font-medium text-slate-900">What's next</p>
          <p className="mt-1">
            The four agents (briefing, KYB intake, early-warning scan and credit memo) arrive in Phase 4. Until then, try the demo agent on any account, or explore the{' '}
            <Link to="/accounts" className="text-brand-700 underline">accounts</Link> and the{' '}
            <Link to="/deals" className="text-brand-700 underline">pipeline</Link>.
          </p>
        </Card>
      </div>
    </>
  )
}
