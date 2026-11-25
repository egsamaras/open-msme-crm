import { useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { useSignals, useUpdateSignal, type Signal } from '@/api/risk'
import { useMe } from '@/auth'
import { ScanPanel } from '@/components/ScanPanel'
import { Tabs } from '@/components/Tabs'
import { Badge, Card, EmptyState, ErrorState, Loading, PageHeader } from '@/components/ui'
import { SCAN_ROLES } from '@/lib/agents'
import { SEVERITY_TONE, TRIGGER_LABEL, describeSignal } from '@/lib/ews'
import { formatDate, titleCase } from '@/lib/format'

const CAN_UPDATE = new Set(['RM', 'CREDIT_OFFICER', 'ADMIN'])

function SignalActions({ signal }: { signal: Signal }) {
  const update = useUpdateSignal(signal.id)
  const [resolving, setResolving] = useState(false)
  const [note, setNote] = useState('')
  const id = `resolve-${signal.id}`

  function resolve(e: FormEvent) {
    e.preventDefault()
    update.mutate({ status: 'RESOLVED', note })
  }

  if (resolving) {
    return (
      <form onSubmit={resolve} className="space-y-2">
        <label htmlFor={id} className="block text-xs text-slate-500">How was it resolved?</label>
        <input id={id} required value={note} onChange={(e) => setNote(e.target.value)} maxLength={2000} className="w-full rounded-lg border border-slate-300 px-2 py-1 text-sm" />
        {update.isError && <p role="alert" className="text-xs text-rose-700">{update.error.message}</p>}
        <div className="flex gap-2">
          <button type="submit" disabled={update.isPending || !note.trim()} className="rounded-lg bg-brand-600 px-2.5 py-1 text-xs font-medium text-white disabled:opacity-60">Resolve</button>
          <button type="button" onClick={() => setResolving(false)} className="text-xs text-slate-500 underline">Cancel</button>
        </div>
      </form>
    )
  }
  return (
    <div className="flex flex-wrap gap-2">
      {signal.status === 'OPEN' && (
        <button type="button" disabled={update.isPending} onClick={() => update.mutate({ status: 'INVESTIGATING' })} className="rounded-lg border border-slate-300 px-2.5 py-1 text-xs hover:bg-slate-50">
          Investigate
        </button>
      )}
      <button type="button" onClick={() => setResolving(true)} className="rounded-lg border border-slate-300 px-2.5 py-1 text-xs hover:bg-slate-50">
        Resolve…
      </button>
    </div>
  )
}

export function RiskPage() {
  const [tab, setTab] = useState<'open' | 'resolved'>('open')
  const signals = useSignals(tab)
  const role = useMe().data?.role ?? ''

  return (
    <>
      <PageHeader title="Risk radar" description="Early-warning alerts from fixed, tested rules, most severe first, with the exact values that fired each one." />
      {SCAN_ROLES.has(role) && <div className="mb-5"><ScanPanel /></div>}
      <Tabs label="Alert state" active={tab} onChange={setTab} tabs={[{ key: 'open', label: 'Open' }, { key: 'resolved', label: 'Resolved' }]} />
      <Card className="mt-5 overflow-hidden">
        {signals.isPending ? (
          <Loading />
        ) : signals.isError ? (
          <ErrorState error={signals.error} onRetry={() => void signals.refetch()} />
        ) : signals.data.length === 0 ? (
          <EmptyState title={tab === 'open' ? 'No open alerts' : 'Nothing resolved yet'}>
            {tab === 'open' && <p>Run a portfolio scan to check accounts against the rules.</p>}
          </EmptyState>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-3 py-3 font-medium">Severity</th>
                  <th className="px-3 py-3 font-medium">Account</th>
                  <th className="px-3 py-3 font-medium">What fired</th>
                  <th className="px-3 py-3 font-medium">Status</th>
                  <th className="px-3 py-3 font-medium">{tab === 'open' ? 'Action' : 'Resolution'}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {signals.data.map((s) => (
                  <tr key={s.id} className="align-top">
                    <td className="px-3 py-3"><Badge tone={SEVERITY_TONE[s.severity]}>{titleCase(s.severity)}</Badge></td>
                    <td className="px-3 py-3">
                      <Link to={`/accounts/${s.company_id}`} className="font-medium hover:underline">{s.company_name}</Link>
                      <div className="text-xs text-slate-500">Detected {formatDate(s.detected_at)}</div>
                    </td>
                    <td className="max-w-md px-3 py-3">
                      <div className="font-medium">{TRIGGER_LABEL[s.trigger]}</div>
                      <div className="text-slate-600">{describeSignal(s.trigger, s.metrics)}</div>
                      {s.root_cause_summary && (
                        <details className="mt-1 text-xs">
                          <summary className="cursor-pointer text-violet-700">Agent's root-cause analysis</summary>
                          <p className="mt-1 text-slate-600">{s.root_cause_summary}</p>
                        </details>
                      )}
                    </td>
                    <td className="px-3 py-3"><Badge tone={s.status === 'INVESTIGATING' ? 'info' : s.status === 'RESOLVED' ? 'good' : 'warn'}>{titleCase(s.status)}</Badge></td>
                    <td className="px-3 py-3">
                      {s.status === 'RESOLVED' ? (
                        <p className="text-xs text-slate-600">
                          {s.resolved_by_name} on {formatDate(s.resolved_at)}
                          {s.resolution_note && <>: “{s.resolution_note}”</>}
                        </p>
                      ) : CAN_UPDATE.has(role) ? (
                        <SignalActions signal={s} />
                      ) : (
                        <span className="text-xs text-slate-400">View only</span>
                      )}
                    </td>
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
