import { Radar } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import { useQueryClient } from '@tanstack/react-query'
import { useAgentRun, useRunStream } from '@/api/agents'
import { useChildRuns, useStartScan } from '@/api/risk'
import { useMe } from '@/auth'
import { TraceTimeline } from '@/components/InspectionDrawer'
import { Badge, Card } from '@/components/ui'
import { RUN_TONE } from '@/lib/agents'
import { titleCase } from '@/lib/format'

/** "Run portfolio scan" with live progress: the rules pass, then one review per flagged company. */
export function ScanPanel({ compact = false }: { compact?: boolean }) {
  const qc = useQueryClient()
  const wholeBank = useMe().data?.role !== 'RM'
  const start = useStartScan()
  const [runId, setRunId] = useState<string | null>(null)
  const { events, status } = useRunStream(runId)
  const parentDone = status === 'COMPLETED'
  const parent = useAgentRun(parentDone ? runId : null)
  const children = useChildRuns(parentDone ? runId : null)
  const result = parent.data?.result as { signals_found?: number; new_signals?: number } | null | undefined
  const stillRunning = status === 'RUNNING' || (children.data?.some((c) => c.status === 'RUNNING') ?? false)
  const settled = parentDone && children.isSuccess && !stillRunning

  // Once every review has paused or finished, the alert lists and KPIs are stale.
  useEffect(() => {
    if (!settled) return
    for (const key of ['ews', 'accounts', 'approvals']) void qc.invalidateQueries({ queryKey: [key] })
  }, [settled, qc])

  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-sm font-semibold">
            <Radar className="size-4 text-brand-600" aria-hidden /> Portfolio scan
          </h2>
          {!compact && (
            <p className="text-xs text-slate-500">
              Fixed rules check {wholeBank ? 'every account in the bank' : 'your accounts'}. Each company with a new alert gets its own agent review, which waits for your approval.
            </p>
          )}
        </div>
        <button
          type="button"
          disabled={start.isPending || stillRunning}
          onClick={() =>
            start.mutate(undefined, {
              onSuccess: (run) => {
                setRunId(run.id)
                void qc.invalidateQueries({ queryKey: ['ews'] })
              },
            })
          }
          className="rounded-lg bg-brand-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60"
        >
          {stillRunning && runId ? 'Scanning…' : 'Run portfolio scan'}
        </button>
      </div>
      {start.isError && <p role="alert" className="mt-3 text-sm text-rose-700">{start.error.message}</p>}
      {runId && (
        <div className="mt-4 space-y-3" aria-live="polite">
          <TraceTimeline trace={events} />
          {status === 'FAILED' && <Badge tone="bad">Scan failed</Badge>}
          {parentDone && result && (
            <p className="text-sm text-slate-700">
              {result.signals_found} alert{result.signals_found === 1 ? '' : 's'} across {wholeBank ? 'the bank' : 'your accounts'}, {result.new_signals} new.
              {result.new_signals === 0 && ' Nothing new to review.'}
            </p>
          )}
          {children.data && children.data.length > 0 && (
            <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200 text-sm">
              {children.data.map((c) => (
                <li key={c.id} className="flex items-center justify-between gap-2 px-3 py-2">
                  <Link to={`/accounts/${c.company_id}`} className="hover:underline">{c.company_name}</Link>
                  <Badge tone={RUN_TONE[c.status]}>{c.status === 'AWAITING_APPROVAL' ? 'Waiting for approval' : titleCase(c.status)}</Badge>
                </li>
              ))}
            </ul>
          )}
          {children.data?.some((c) => c.status === 'AWAITING_APPROVAL') && (
            <Link to="/approvals" className="inline-block text-sm font-medium text-brand-700 underline">Review the proposals</Link>
          )}
        </div>
      )}
    </Card>
  )
}
