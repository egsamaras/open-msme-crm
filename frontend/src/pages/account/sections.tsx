import { useState, type FormEvent, type ReactNode } from 'react'
import { Link } from 'react-router'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  useAccountEws,
  useAccountTasks,
  useDeals,
  useDocuments,
  useFacilities,
  useFinancials,
  useInteractions,
  useLogInteraction,
  type AccountDetail,
  type Facility,
  type InteractionIn,
} from '@/api/queries'
import { DemoAgentPanel } from '@/components/DemoAgentPanel'
import { InspectionDrawer } from '@/components/InspectionDrawer'
import { CheckButton, KYB_ROLES, UploadForm } from '@/components/KybPanel'
import { TaskList } from '@/components/TaskList'
import { useAppInfo, useMe } from '@/auth'
import { Badge, Card, EmptyState, ErrorState, Loading } from '@/components/ui'
import {
  daysUntil,
  DOC_LABEL,
  formatDate,
  formatDayMonth,
  formatMoney,
  formatMonth,
  formatPct,
  formatRatio,
  PRODUCT_LABEL,
  STAGE_LABEL,
  titleCase,
  toNumber,
} from '@/lib/format'

type Props = { account: AccountDetail }

const CHART = { brand: '#2f7d7a', muted: '#94a3b8', alert: '#e11d48', grid: '#e2e8f0' }

function Section({ title, children, aside }: { title: string; children: ReactNode; aside?: ReactNode }) {
  return (
    <Card className="p-5">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">{title}</h2>
        {aside}
      </div>
      {children}
    </Card>
  )
}

function QueryState({ q, children }: { q: { isPending: boolean; isError: boolean; error: unknown; refetch: () => unknown }; children: () => ReactNode }) {
  if (q.isPending) return <Loading />
  if (q.isError) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />
  return <>{children()}</>
}

// ---------- Overview ----------

export function OverviewTab({ account }: Props) {
  const tasks = useAccountTasks(account.id)
  const deals = useDeals(account.id)
  const info = useAppInfo()
  const me = useMe()
  const showDemo = info.data?.dev_persona_switch && (me.data?.role === 'RM' || me.data?.role === 'ADMIN')
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {showDemo && (
        <div className="lg:col-span-2">
          <DemoAgentPanel companyId={account.id} />
        </div>
      )}
      <Section title="Open tasks">
        <QueryState q={tasks}>
          {() => <TaskList tasks={(tasks.data ?? []).filter((t) => t.status === 'OPEN')} showCompany={false} />}
        </QueryState>
      </Section>
      <Section title="Pipeline">
        <QueryState q={deals}>
          {() =>
            deals.data!.length === 0 ? (
              <EmptyState title="No deals for this account" />
            ) : (
              <ul className="divide-y divide-slate-100 text-sm">
                {deals.data!.map((d) => (
                  <li key={d.id} className="flex items-center justify-between gap-3 py-2">
                    <div>
                      <div className="font-medium">{PRODUCT_LABEL[d.product]}</div>
                      <div className="text-xs text-slate-500">Expected {formatDate(d.expected_close)}</div>
                    </div>
                    <div className="text-right">
                      <div className="tabular-nums">{formatMoney(d.requested_amount, d.currency)}</div>
                      <Badge tone={d.stage === 'LOST' ? 'bad' : d.stage === 'DISBURSED' ? 'good' : 'info'}>{STAGE_LABEL[d.stage]}</Badge>
                    </div>
                  </li>
                ))}
              </ul>
            )
          }
        </QueryState>
      </Section>
      <Section title="Contacts">
        <ul className="divide-y divide-slate-100 text-sm">
          {account.contacts.map((c) => (
            <li key={c.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <div>
                <span className="font-medium">{c.full_name}</span>
                {c.is_primary && <span className="ml-2"><Badge tone="info">Primary</Badge></span>}
                <div className="text-xs text-slate-500">{c.title}</div>
              </div>
              <div className="text-right text-xs text-slate-500">
                <div>{c.email}</div>
                <div>{c.phone}</div>
              </div>
            </li>
          ))}
        </ul>
      </Section>
    </div>
  )
}

// ---------- Facilities ----------

function FacilityCard({ f, currency }: { f: Facility; currency: string }) {
  const pct = f.utilization_pct === null ? null : toNumber(f.utilization_pct)
  const threshold = toNumber(f.alert_threshold_pct)
  const data = f.history.map((p) => ({ date: p.as_of, pct: p.utilization_pct === null ? null : toNumber(p.utilization_pct) }))
  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="font-semibold">
            {PRODUCT_LABEL[f.product]}
            {f.is_islamic && <span className="ml-2 align-middle"><Badge tone="info">Islamic</Badge></span>}
          </h3>
          <p className="text-xs text-slate-500">
            {formatPct(toNumber(f.rate_pct), 2)} {f.is_islamic ? 'profit rate' : 'interest'} · matures {formatDate(f.maturity_date)}
          </p>
        </div>
        <div className="text-right">
          <div className="text-lg font-semibold tabular-nums">{formatPct(pct)}</div>
          <div className="text-xs text-slate-500 tabular-nums">
            {formatMoney(f.utilized_amount, currency)} of {formatMoney(f.sanctioned_limit, currency)}
          </div>
        </div>
      </div>
      {f.days_above_alert_threshold > 0 && (
        <p className="mt-3 rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-800">
          Above {threshold}% for {f.days_above_alert_threshold} days in a row.
        </p>
      )}
      <div className="mt-4 h-40" role="img" aria-label={`Weekly utilisation for the last ${data.length} weeks, currently ${formatPct(pct)}`}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 5, right: 8, bottom: 0, left: -18 }}>
            <CartesianGrid stroke={CHART.grid} vertical={false} />
            <XAxis dataKey="date" tickFormatter={formatDayMonth} tick={{ fontSize: 11 }} minTickGap={40} />
            <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} unit="%" />
            <Tooltip formatter={(v) => [formatPct(Number(v), 1), 'Utilisation']} labelFormatter={(l) => formatDate(String(l))} />
            <ReferenceLine y={threshold} stroke={CHART.alert} strokeDasharray="4 4" />
            <Line type="monotone" dataKey="pct" stroke={CHART.brand} strokeWidth={2} dot={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      {f.covenants.length > 0 && (
        <div className="mt-3 border-t border-slate-100 pt-3 text-sm">
          {f.covenants.map((c) => (
            <div key={`${c.metric}${c.operator}${c.threshold}`} className="flex items-center justify-between gap-2">
              <span>
                Covenant: {c.metric} {c.operator} {c.threshold}
                <span className="ml-1 text-xs text-slate-500">(actual {formatRatio(c.actual)}, {formatDate(c.tested_on)})</span>
              </span>
              {c.passes === null ? <Badge>Not testable</Badge> : c.passes ? <Badge tone="good">Pass</Badge> : <Badge tone="bad">Breach</Badge>}
            </div>
          ))}
        </div>
      )}
    </Card>
  )
}

export function FacilitiesTab({ account }: Props) {
  const facilities = useFacilities(account.id)
  return (
    <QueryState q={facilities}>
      {() =>
        facilities.data!.length === 0 ? (
          <Card><EmptyState title="No facilities" /></Card>
        ) : (
          <div className="grid gap-4 xl:grid-cols-2">
            {facilities.data!.map((f) => <FacilityCard key={f.id} f={f} currency={account.currency} />)}
          </div>
        )
      }
    </QueryState>
  )
}

// ---------- Financials ----------

export function FinancialsTab({ account }: Props) {
  const fin = useFinancials(account.id)
  const money = (v: unknown) => formatMoney(Number(v), account.currency, true)
  return (
    <QueryState q={fin}>
      {() => {
        const rows = fin.data!
        if (rows.length === 0) return <Card><EmptyState title="No financial snapshots yet" /></Card>
        const data = rows.map((r) => ({
          month: formatMonth(r.period_end),
          revenue: toNumber(r.revenue),
          ebitda: toNumber(r.ebitda),
          balance: toNumber(r.avg_bank_balance),
        }))
        return (
          <div className="space-y-4">
            <div className="grid gap-4 lg:grid-cols-2">
              <Section title="Revenue and EBITDA (monthly)">
                <div className="h-56" role="img" aria-label="Monthly revenue and EBITDA bar chart">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={data} margin={{ top: 5, right: 8, bottom: 0, left: 8 }}>
                      <CartesianGrid stroke={CHART.grid} vertical={false} />
                      <XAxis dataKey="month" tick={{ fontSize: 11 }} />
                      <YAxis tickFormatter={money} tick={{ fontSize: 11 }} width={70} />
                      <Tooltip formatter={(v, n) => [money(v), n === 'revenue' ? 'Revenue' : 'EBITDA']} />
                      <Legend formatter={(n) => (n === 'revenue' ? 'Revenue' : 'EBITDA')} />
                      <Bar dataKey="revenue" fill={CHART.muted} radius={[3, 3, 0, 0]} isAnimationActive={false} />
                      <Bar dataKey="ebitda" fill={CHART.brand} radius={[3, 3, 0, 0]} isAnimationActive={false} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </Section>
              <Section title="Average bank balance">
                <div className="h-56" role="img" aria-label="Monthly average bank balance line chart">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={data} margin={{ top: 5, right: 8, bottom: 0, left: 8 }}>
                      <CartesianGrid stroke={CHART.grid} vertical={false} />
                      <XAxis dataKey="month" tick={{ fontSize: 11 }} />
                      <YAxis tickFormatter={money} tick={{ fontSize: 11 }} width={70} />
                      <Tooltip formatter={(v) => [money(v), 'Average balance']} />
                      <Line type="monotone" dataKey="balance" stroke={CHART.brand} strokeWidth={2} isAnimationActive={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </Section>
            </div>
            <Section title="Ratios" aside={<span className="text-xs text-slate-500">Computed from raw inputs, never stored</span>}>
              <div className="overflow-x-auto">
                <table className="w-full text-right text-sm tabular-nums">
                  <thead className="text-xs uppercase tracking-wide text-slate-500">
                    <tr>
                      <th className="py-2 text-left font-medium">Month</th>
                      <th className="py-2 font-medium">DSCR</th>
                      <th className="py-2 font-medium">Debt / equity</th>
                      <th className="py-2 font-medium">Debt / EBITDA</th>
                      <th className="py-2 font-medium">Current ratio</th>
                      <th className="py-2 font-medium">Balance Δ</th>
                      <th className="py-2 font-medium">Bounced</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {rows.map((r) => {
                      const change = r.balance_change_pct === null ? null : toNumber(r.balance_change_pct)
                      return (
                        <tr key={r.id}>
                          <td className="py-2 text-left">{formatMonth(r.period_end)}</td>
                          <td className={r.dscr !== null && toNumber(r.dscr) < 1.25 ? 'py-2 text-rose-700' : 'py-2'}>{formatRatio(r.dscr)}</td>
                          <td className="py-2">{formatRatio(r.debt_to_equity)}</td>
                          <td className="py-2">{formatRatio(r.debt_to_ebitda)}</td>
                          <td className="py-2">{formatRatio(r.current_ratio)}</td>
                          <td className={change !== null && change <= -20 ? 'py-2 text-rose-700' : 'py-2'}>
                            {change === null ? '—' : `${change > 0 ? '+' : ''}${change.toFixed(1)}%`}
                          </td>
                          <td className={r.bounced_cheques > 0 ? 'py-2 font-medium text-rose-700' : 'py-2'}>{r.bounced_cheques}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </Section>
          </div>
        )
      }}
    </QueryState>
  )
}

// ---------- Owners & documents ----------

export function DocumentsTab({ account }: Props) {
  const docs = useDocuments(account.id)
  const canCheck = KYB_ROLES.has(useMe().data?.role ?? '')
  const [inspect, setInspect] = useState<string | null>(null)
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Section title="Beneficial owners" aside={<span className="text-xs text-slate-500">UBO at {account.ubo_threshold_pct}% or more</span>}>
        <ul className="divide-y divide-slate-100 text-sm">
          {account.owners.map((o) => (
            <li key={o.id} className="flex items-center justify-between gap-2 py-2">
              <div>
                <span className="font-medium">{o.full_name}</span>
                {o.is_ubo && <span className="ml-2"><Badge tone="info">UBO</Badge></span>}
                <div className="text-xs text-slate-500">
                  PEP {titleCase(o.pep_status).toLowerCase()} · sanctions {titleCase(o.sanctions_status).toLowerCase()}
                </div>
              </div>
              <span className="tabular-nums">{toNumber(o.ownership_pct).toFixed(0)}%</span>
            </li>
          ))}
        </ul>
      </Section>
      <Section title="Documents">
        <QueryState q={docs}>
          {() =>
            docs.data!.length === 0 ? (
              <EmptyState title="No documents on file" />
            ) : (
              <ul className="divide-y divide-slate-100 text-sm">
                {docs.data!.map((d) => {
                  const days = d.expiry_date ? daysUntil(d.expiry_date) : null
                  const waiting = d.check_run_status === 'AWAITING_APPROVAL' || d.check_run_status === 'RUNNING'
                  return (
                    <li key={d.id} className="py-2">
                      <div className="flex items-center justify-between gap-2">
                        <div>
                          <div className="font-medium">{DOC_LABEL[d.doc_type]}</div>
                          <div className="text-xs text-slate-500">
                            {d.file_name}
                            {d.expiry_date && ` · expires ${formatDate(d.expiry_date)}`}
                          </div>
                        </div>
                        <div className="flex gap-1">
                          {days !== null && days < 0 && <Badge tone="bad">Expired</Badge>}
                          {days !== null && days >= 0 && days <= 30 && <Badge tone="warn">{days} days left</Badge>}
                          <Badge tone={d.verification_status === 'VERIFIED' ? 'good' : d.verification_status === 'REJECTED' ? 'bad' : 'warn'}>
                            {titleCase(d.verification_status)}
                          </Badge>
                        </div>
                      </div>
                      {waiting ? (
                        <p className="mt-1 text-xs text-amber-800">
                          KYB check {d.check_run_status === 'RUNNING' ? 'running' : 'waiting for compliance review'} ·{' '}
                          <Link to="/approvals" className="underline">Approvals</Link> ·{' '}
                          <button type="button" onClick={() => setInspect(d.check_run_id ?? null)} className="underline">Inspect</button>
                        </p>
                      ) : (
                        canCheck && d.has_text && d.verification_status === 'PENDING' && (
                          <div className="mt-1"><CheckButton companyId={account.id} documentId={d.id} /></div>
                        )
                      )}
                    </li>
                  )
                })}
              </ul>
            )
          }
        </QueryState>
        {canCheck && <UploadForm companyId={account.id} />}
      </Section>
      {inspect && <InspectionDrawer runId={inspect} onClose={() => setInspect(null)} />}
    </div>
  )
}

// ---------- Interactions ----------

function nowLocalInput(): string {
  const d = new Date()
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset())
  return d.toISOString().slice(0, 16)
}

function LogInteractionForm({ companyId }: { companyId: string }) {
  const log = useLogInteraction(companyId)
  const [type, setType] = useState<InteractionIn['interaction_type']>('CALL')
  const [when, setWhen] = useState(nowLocalInput)
  const [summary, setSummary] = useState('')
  const [notes, setNotes] = useState('')

  function submit(e: FormEvent) {
    e.preventDefault()
    log.mutate(
      { interaction_type: type, occurred_at: new Date(when).toISOString(), summary, notes: notes || null },
      { onSuccess: () => { setSummary(''); setNotes('') } },
    )
  }

  return (
    <form onSubmit={submit} className="space-y-3 text-sm">
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block">
          <span className="text-xs text-slate-500">Type</span>
          <select value={type} onChange={(e) => setType(e.target.value as typeof type)} className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5">
            <option value="CALL">Call</option>
            <option value="MEETING">Meeting</option>
            <option value="EMAIL">Email</option>
            <option value="SITE_VISIT">Site visit</option>
          </select>
        </label>
        <label className="block">
          <span className="text-xs text-slate-500">When</span>
          <input type="datetime-local" value={when} max={nowLocalInput()} onChange={(e) => setWhen(e.target.value)} required className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5" />
        </label>
      </div>
      <label className="block">
        <span className="text-xs text-slate-500">Summary</span>
        <input value={summary} onChange={(e) => setSummary(e.target.value)} minLength={3} maxLength={500} required className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5" />
      </label>
      <label className="block">
        <span className="text-xs text-slate-500">Notes (optional)</span>
        <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} maxLength={5000} className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5" />
      </label>
      {log.isError && <p role="alert" className="text-rose-700">{log.error.message}</p>}
      <button type="submit" disabled={log.isPending} className="rounded-lg bg-brand-600 px-4 py-2 font-medium text-white hover:bg-brand-700 disabled:opacity-60">
        {log.isPending ? 'Saving…' : 'Log interaction'}
      </button>
    </form>
  )
}

export function InteractionsTab({ account }: Props) {
  const interactions = useInteractions(account.id)
  return (
    <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
      <Section title="History">
        <QueryState q={interactions}>
          {() =>
            interactions.data!.length === 0 ? (
              <EmptyState title="No interactions logged" />
            ) : (
              <ol className="space-y-4 text-sm">
                {interactions.data!.map((i) => (
                  <li key={i.id} className="border-l-2 border-brand-100 pl-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge>{titleCase(i.interaction_type)}</Badge>
                      <span className="text-xs text-slate-500">{formatDate(i.occurred_at)} · {i.user_name ?? 'Unknown'}</span>
                    </div>
                    <p className="mt-1 font-medium">{i.summary}</p>
                    {i.notes && <p className="mt-0.5 whitespace-pre-line text-slate-600">{i.notes}</p>}
                  </li>
                ))}
              </ol>
            )
          }
        </QueryState>
      </Section>
      <Section title="Log an interaction">
        <LogInteractionForm companyId={account.id} />
      </Section>
    </div>
  )
}

// ---------- Alerts ----------

export function EwsTab({ account }: Props) {
  const ews = useAccountEws(account.id)
  return (
    <Card>
      <QueryState q={ews}>
        {() =>
          ews.data!.length === 0 ? (
            <EmptyState title="No early-warning alerts">
              <p>Alerts appear here after a portfolio scan.</p>
            </EmptyState>
          ) : (
            <ul className="divide-y divide-slate-100 text-sm">
              {ews.data!.map((e) => (
                <li key={e.id} className="flex items-center justify-between gap-2 p-4">
                  <span>{titleCase(e.trigger)}</span>
                  <Badge tone={e.severity === 'CRITICAL' || e.severity === 'HIGH' ? 'bad' : 'warn'}>{titleCase(e.severity)}</Badge>
                </li>
              ))}
            </ul>
          )
        }
      </QueryState>
    </Card>
  )
}
