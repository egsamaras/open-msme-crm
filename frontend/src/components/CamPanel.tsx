import { FileText } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useRunStream } from '@/api/agents'
import { api, unwrap } from '@/api/client'
import type { DealDetail } from '@/api/queries'
import { useMe } from '@/auth'
import { CamView } from '@/components/CamView'
import { gradeTone } from '@/lib/cam'
import { InspectionDrawer, TraceTimeline } from '@/components/InspectionDrawer'
import { Badge } from '@/components/ui'

const STARTERS = new Set(['RM', 'ADMIN'])

/** Draft a credit memo for a deal in underwriting, or show the one a credit officer approved. */
export function CamPanel({ deal }: { deal: DealDetail }) {
  const qc = useQueryClient()
  const role = useMe().data?.role ?? ''
  const [runId, setRunId] = useState<string | null>(null)
  const [inspect, setInspect] = useState<string | null>(null)
  const { events, status } = useRunStream(runId)
  const start = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST('/api/agents/cam/{deal_id}', { params: { path: { deal_id: deal.id } } })),
    onSuccess: (run) => setRunId(run.id),
  })
  const waiting = deal.cam_run_status === 'AWAITING_APPROVAL' || status === 'AWAITING_APPROVAL'

  if (deal.draft_cam) {
    return (
      <section>
        <div className="mb-2 flex items-center justify-between gap-2">
          <h3 className="font-semibold">Credit memo</h3>
          <Badge tone={gradeTone(deal.draft_cam.risk_grade)}>Grade {deal.draft_cam.risk_grade}/10</Badge>
        </div>
        <p className="mb-3 text-xs text-slate-500">Approved for submission by {deal.credit_officer_name ?? 'a credit officer'}, who now owns the credit decision.</p>
        <CamView cam={deal.draft_cam} />
      </section>
    )
  }
  if (deal.stage !== 'CREDIT_UNDERWRITING') return null

  return (
    <section className="space-y-3">
      <h3 className="font-semibold">Credit memo</h3>
      {waiting ? (
        <p className="rounded-lg bg-amber-50 px-3 py-2 text-amber-900">
          A draft memo is waiting for a credit officer's review.{' '}
          <Link to="/approvals" className="underline">Open Approvals</Link>
          {deal.cam_run_id && (
            <>
              {' · '}
              <button type="button" onClick={() => setInspect(deal.cam_run_id!)} className="underline">Inspect the run</button>
            </>
          )}
        </p>
      ) : STARTERS.has(role) ? (
        <>
          <button
            type="button"
            disabled={start.isPending || status === 'RUNNING'}
            onClick={() => start.mutate()}
            className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-violet-600 px-4 py-2 font-medium text-white hover:bg-violet-700 disabled:opacity-60"
          >
            <FileText className="size-4" aria-hidden /> {status === 'RUNNING' ? 'Drafting…' : 'Draft credit memo'}
          </button>
          <p className="text-xs text-slate-500">The agent computes the ratios, compares them with industry medians and drafts the memo. A credit officer who isn't you reviews it.</p>
        </>
      ) : (
        <p className="text-slate-500">A relationship manager drafts the memo for this deal.</p>
      )}
      {start.isError && <p role="alert" className="text-rose-700">{start.error.message}</p>}
      {runId && (
        <div aria-live="polite" className="space-y-2">
          <TraceTimeline trace={events} />
          {status && status !== 'RUNNING' && (
            <p className="text-sm">
              {status === 'FAILED' ? <Badge tone="bad">Failed</Badge> : status === 'AWAITING_APPROVAL' ? 'Sent for four-eyes review.' : null}{' '}
              <button type="button" className="underline" onClick={() => { void qc.invalidateQueries({ queryKey: ['deals'] }); setInspect(runId) }}>
                See the draft
              </button>
            </p>
          )}
        </div>
      )}
      {inspect && <InspectionDrawer runId={inspect} onClose={() => setInspect(null)} />}
    </section>
  )
}
