import { Sparkles } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import { useRunStream, useStartDemoAgent } from '@/api/agents'
import { TraceTimeline } from '@/components/InspectionDrawer'
import { Badge, Card } from '@/components/ui'
import { titleCase } from '@/lib/format'

/** Development only: run the demo agent on this account and watch it live. */
export function DemoAgentPanel({ companyId }: { companyId: string }) {
  const start = useStartDemoAgent(companyId)
  const [runId, setRunId] = useState<string | null>(null)
  const { events, status } = useRunStream(runId)

  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-sm font-semibold">
            <Sparkles className="size-4 text-violet-600" aria-hidden /> Suggest a follow-up
          </h2>
          <p className="text-xs text-slate-500">Demo agent: reads this account, drafts one task with citations, then waits for your approval.</p>
        </div>
        <button
          type="button"
          disabled={start.isPending || status === 'RUNNING'}
          onClick={() => start.mutate(undefined, { onSuccess: (run) => setRunId(run.id) })}
          className="rounded-lg bg-violet-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-violet-700 disabled:opacity-60"
        >
          {status === 'RUNNING' ? 'Running…' : 'Run agent'}
        </button>
      </div>
      {start.isError && <p role="alert" className="mt-3 text-sm text-rose-700">{start.error.message}</p>}
      {runId && (
        <div className="mt-4 space-y-3" aria-live="polite">
          <TraceTimeline trace={events} />
          {status && status !== 'RUNNING' && (
            <p className="flex flex-wrap items-center gap-2 text-sm">
              <Badge tone={status === 'AWAITING_APPROVAL' ? 'warn' : status === 'FAILED' ? 'bad' : 'good'}>{titleCase(status)}</Badge>
              {status === 'AWAITING_APPROVAL' && <Link to="/approvals" className="text-brand-700 underline">Review it in Approvals</Link>}
            </p>
          )}
        </div>
      )}
    </Card>
  )
}
