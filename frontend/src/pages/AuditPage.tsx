import { Bot, ShieldAlert, ShieldCheck, User } from 'lucide-react'
import { useAuditEvents, useAuditVerify } from '@/api/agents'
import { Card, EmptyState, ErrorState, Loading, PageHeader } from '@/components/ui'

function ChainStatus() {
  const verify = useAuditVerify()
  if (verify.isPending) return <Loading label="Checking the hash chain…" />
  if (verify.isError) return <ErrorState error={verify.error} onRetry={() => void verify.refetch()} />
  const ok = verify.data.ok
  return (
    <div role="status" className={`flex items-start gap-3 rounded-xl p-4 text-sm ${ok ? 'bg-emerald-50 text-emerald-900' : 'bg-rose-50 text-rose-900'}`}>
      {ok ? <ShieldCheck className="mt-0.5 size-5 shrink-0" aria-hidden /> : <ShieldAlert className="mt-0.5 size-5 shrink-0" aria-hidden />}
      <div>
        <p className="font-medium">{ok ? 'Hash chain intact' : `Chain broken at event #${verify.data.first_bad_seq}`}</p>
        <p className="mt-0.5">
          {verify.data.events_checked} events checked. Each event's SHA-256 hash covers the one before it, and the database
          refuses edits and deletes, so a gap or change would show here.
        </p>
      </div>
      <button type="button" onClick={() => void verify.refetch()} className="ml-auto shrink-0 underline">Re-check</button>
    </div>
  )
}

export function AuditPage() {
  const events = useAuditEvents()
  const rows = events.data?.pages.flat() ?? []
  return (
    <>
      <PageHeader title="Audit trail" description="Every sign-in, change, agent proposal and human decision, newest first." />
      <ChainStatus />
      <Card className="mt-4 overflow-hidden">
        {events.isPending ? (
          <Loading />
        ) : events.isError ? (
          <ErrorState error={events.error} onRetry={() => void events.refetch()} />
        ) : rows.length === 0 ? (
          <EmptyState title="No events yet" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-3 py-3 font-medium">#</th>
                  <th className="px-3 py-3 font-medium">When</th>
                  <th className="px-3 py-3 font-medium">Who</th>
                  <th className="px-3 py-3 font-medium">Action</th>
                  <th className="px-3 py-3 font-medium">Details</th>
                  <th className="px-3 py-3 font-medium">Hash</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {rows.map((e) => (
                  <tr key={e.seq} className="align-top">
                    <td className="px-3 py-2 tabular-nums text-slate-400">{e.seq}</td>
                    <td className="whitespace-nowrap px-3 py-2 tabular-nums">
                      {new Date(e.occurred_at).toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                    </td>
                    <td className="px-3 py-2">
                      {e.actor_agent ? (
                        <span className="inline-flex items-center gap-1 text-violet-700"><Bot className="size-3.5" aria-hidden /> {e.actor_agent}{e.actor_name && <span className="text-slate-500"> for {e.actor_name}</span>}</span>
                      ) : (
                        <span className="inline-flex items-center gap-1"><User className="size-3.5 text-slate-400" aria-hidden /> {e.actor_name ?? 'system'}</span>
                      )}
                    </td>
                    <td className="px-3 py-2"><code className="text-xs">{e.action}</code></td>
                    <td className="px-3 py-2">
                      <details>
                        <summary className="cursor-pointer whitespace-nowrap text-xs text-slate-500">{e.entity_type.replace('_', ' ')}</summary>
                        <pre className="mt-1 max-w-md overflow-auto rounded bg-slate-50 p-2 text-xs">{JSON.stringify(e.payload, null, 2)}</pre>
                      </details>
                    </td>
                    <td className="px-3 py-2"><code className="text-xs text-slate-400" title={e.hash}>{e.hash.slice(0, 10)}…</code></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {events.hasNextPage && (
          <div className="border-t border-slate-100 p-3 text-center">
            <button type="button" disabled={events.isFetchingNextPage} onClick={() => void events.fetchNextPage()} className="text-sm text-brand-700 underline">
              {events.isFetchingNextPage ? 'Loading…' : 'Load older events'}
            </button>
          </div>
        )}
      </Card>
    </>
  )
}
