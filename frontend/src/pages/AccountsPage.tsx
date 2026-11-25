import { Search } from 'lucide-react'
import { useDeferredValue, useState } from 'react'
import { Link } from 'react-router'
import type { AccountListItem, Role } from '@/api/client'
import { useMe } from '@/auth'
import { Badge, Card, EmptyState, ErrorState, Loading, PageHeader } from '@/components/ui'
import { daysUntil, formatDate, formatMoney, formatPct, percentOf, titleCase } from '@/lib/format'
import { useAccounts } from './accounts'

const KYB_TONE = { VERIFIED: 'good', PENDING_RENEWAL: 'warn', FLAGGED: 'bad' } as const

const DESCRIPTION: Record<Role, string> = {
  RM: 'The accounts assigned to you.',
  CREDIT_OFFICER: 'Every account in the bank, most alerts and highest risk first.',
  COMPLIANCE: 'Every account in the bank, KYB issues first, then the soonest document expiry.',
  ADMIN: 'Every account in the bank.',
}

function Expiry({ date }: { date: string | null | undefined }) {
  if (!date) return <span className="text-slate-400">—</span>
  const days = daysUntil(date)
  return days > 30 ? <span>{formatDate(date)}</span> : <Badge tone={days < 0 ? 'bad' : 'warn'}>{formatDate(date)}</Badge>
}

function UtilisationBar({ row }: { row: AccountListItem }) {
  const pct = percentOf(row.total_utilized, row.total_limit)
  const tone = pct === null ? 'bg-slate-300' : pct >= 90 ? 'bg-rose-500' : pct >= 75 ? 'bg-amber-500' : 'bg-brand-500'
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-slate-100" aria-hidden>
        <div className={`h-full ${tone}`} style={{ width: `${Math.min(pct ?? 0, 100)}%` }} />
      </div>
      <span className="tabular-nums text-slate-600">{formatPct(pct)}</span>
    </div>
  )
}

export function AccountsPage() {
  const [q, setQ] = useState('')
  const deferred = useDeferredValue(q.trim())
  const accounts = useAccounts(deferred)
  const role = useMe().data?.role ?? 'RM'
  const wholeBank = role !== 'RM'
  const compliance = role === 'COMPLIANCE'

  return (
    <>
      <PageHeader
        title="Accounts"
        description={`${DESCRIPTION[role]}${accounts.data && !deferred ? ` ${accounts.data.length} accounts.` : ''} Amounts are in each client's own currency.`}
        actions={
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-2.5 size-4 text-slate-400" aria-hidden />
            <input
              type="search"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search name or CR number"
              aria-label="Search accounts"
              className="w-72 rounded-lg border border-slate-300 bg-white py-2 pl-9 pr-3 text-sm"
            />
          </div>
        }
      />
      <Card className="overflow-hidden">
        {accounts.isPending ? (
          <Loading label="Loading accounts…" />
        ) : accounts.isError ? (
          <ErrorState error={accounts.error} onRetry={() => void accounts.refetch()} />
        ) : accounts.data.length === 0 ? (
          <EmptyState title="No accounts match">Try a different name or CR number.</EmptyState>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-3 py-3 font-medium">Company</th>
                  <th className="hidden px-3 py-3 font-medium lg:table-cell">Segment</th>
                  <th className="px-3 py-3 text-right font-medium">Total limits</th>
                  {compliance ? <th className="px-3 py-3 font-medium">Next expiry</th> : <th className="px-3 py-3 font-medium">Utilisation</th>}
                  <th className="px-3 py-3 font-medium">Risk</th>
                  <th className="px-3 py-3 font-medium">KYB</th>
                  <th className="px-3 py-3 font-medium">Alerts</th>
                  {wholeBank && <th className="px-3 py-3 font-medium">RM</th>}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {accounts.data.map((a) => (
                  <tr key={a.id} className="hover:bg-slate-50">
                    <td className="min-w-44 px-3 py-3">
                      <Link to={`/accounts/${a.id}`} className="font-medium text-brand-700 hover:underline">
                        {a.trading_name ?? a.legal_name}
                      </Link>
                      <div className="whitespace-nowrap text-xs text-slate-500">
                        {a.cr_number} · {a.country}
                      </div>
                    </td>
                    <td className="hidden px-3 py-3 lg:table-cell">
                      <div>{titleCase(a.tier)}</div>
                      <div className="text-xs text-slate-500">{a.industry}</div>
                    </td>
                    <td className="whitespace-nowrap px-3 py-3 text-right tabular-nums">
                      {formatMoney(a.total_limit, a.currency)}
                    </td>
                    <td className="px-3 py-3">
                      {compliance ? <Expiry date={a.next_doc_expiry} /> : <UtilisationBar row={a} />}
                    </td>
                    <td className="px-3 py-3 tabular-nums">{a.risk_rating}/10</td>
                    <td className="px-3 py-3">
                      <Badge tone={KYB_TONE[a.kyb_status]}>{titleCase(a.kyb_status)}</Badge>
                    </td>
                    <td className="px-3 py-3">
                      {a.open_ews > 0 ? <Badge tone="bad">{a.open_ews} open</Badge> : <span className="text-slate-400">—</span>}
                    </td>
                    {wholeBank && <td className="whitespace-nowrap px-3 py-3">{a.rm_name ?? '—'}</td>}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  )
}
