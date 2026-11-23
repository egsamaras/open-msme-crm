import { Sparkles, X } from 'lucide-react'
import { useEffect, useId, useRef, useState } from 'react'
import { useAgentRun, useRunStream, useStartBriefing } from '@/api/agents'
import { InspectionDrawer, TraceTimeline } from '@/components/InspectionDrawer'
import { Badge, ErrorState } from '@/components/ui'
import { HEALTH, type Briefing } from '@/lib/briefing'
import { PRODUCT_LABEL } from '@/lib/format'

function BriefingView({ b }: { b: Briefing }) {
  const h = HEALTH[b.metrics.health]
  return (
    <div className="space-y-5">
      <div>
        <Badge tone={h.tone}>{h.label}</Badge>
        <p className="mt-2 text-base font-medium">{b.briefing.headline}</p>
      </div>
      <section>
        <h3 className="mb-1 font-semibold">Talking points</h3>
        <ul className="list-disc space-y-1 pl-5">{b.briefing.talking_points.map((t) => <li key={t}>{t}</li>)}</ul>
      </section>
      <section>
        <h3 className="mb-1 font-semibold">Open gaps</h3>
        {b.briefing.gaps.length === 0 ? (
          <p className="text-slate-500">Nothing outstanding on file.</p>
        ) : (
          <ul className="list-disc space-y-1 pl-5">{b.briefing.gaps.map((g) => <li key={g}>{g}</li>)}</ul>
        )}
      </section>
      <section>
        <h3 className="mb-1 font-semibold">Product ideas</h3>
        {b.briefing.product_ideas.length === 0 ? (
          <p className="text-slate-500">No product the rules would put forward right now.</p>
        ) : (
          <ul className="space-y-2">
            {b.briefing.product_ideas.map((p) => (
              <li key={p.product} className="rounded-lg border border-slate-200 p-3">
                <p className="font-medium">{PRODUCT_LABEL[p.product] ?? p.product}</p>
                <p className="mt-0.5 text-slate-600">{p.pitch}</p>
              </li>
            ))}
          </ul>
        )}
        <p className="mt-2 text-xs text-slate-500">Ideas come from fixed rules on the account's figures; the model only writes the pitch.</p>
      </section>
    </div>
  )
}

/** Button that starts a briefing and opens the panel. Started on click, not in an effect. */
export function BriefingButton({ companyId, companyName }: { companyId: string; companyName: string }) {
  const start = useStartBriefing(companyId)
  const [open, setOpen] = useState(false)
  const begin = () => {
    setOpen(true)
    start.mutate()
  }
  return (
    <>
      <button
        type="button"
        onClick={begin}
        className="inline-flex items-center gap-1.5 rounded-lg bg-violet-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-violet-700"
      >
        <Sparkles className="size-4" aria-hidden /> Prepare briefing
      </button>
      {open && (
        <BriefingPanel
          companyName={companyName}
          runId={start.data?.id ?? null}
          error={start.error}
          onRefresh={() => start.mutate()}
          onClose={() => { setOpen(false); start.reset() }}
        />
      )}
    </>
  )
}

/** Slide-over co-pilot: a read-only briefing for a client meeting, built live. */
function BriefingPanel({ companyName, runId, error, onRefresh, onClose }: {
  companyName: string
  runId: string | null
  error: Error | null
  onRefresh: () => void
  onClose: () => void
}) {
  const titleId = useId()
  const closeRef = useRef<HTMLButtonElement>(null)
  const [inspect, setInspect] = useState(false)
  const { events, status } = useRunStream(runId)
  const run = useAgentRun(status === 'COMPLETED' ? runId : null)

  useEffect(() => {
    closeRef.current?.focus()
  }, [])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && !inspect && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [inspect, onClose])

  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <div className="absolute inset-0 bg-slate-900/30" onClick={onClose} aria-hidden />
      <aside role="dialog" aria-modal="true" aria-labelledby={titleId} className="relative flex h-full w-full max-w-lg flex-col overflow-y-auto bg-white shadow-xl">
        <div className="flex items-start justify-between gap-3 border-b border-slate-200 p-5">
          <div>
            <h2 id={titleId} className="flex items-center gap-2 text-lg font-semibold">
              <Sparkles className="size-4 text-violet-600" aria-hidden /> Meeting briefing
            </h2>
            <p className="text-sm text-slate-500">{companyName}</p>
          </div>
          <button ref={closeRef} type="button" onClick={onClose} aria-label="Close" className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100">
            <X className="size-5" aria-hidden />
          </button>
        </div>
        <div className="space-y-5 p-5 text-sm" aria-live="polite">
          {error && <ErrorState error={error} onRetry={onRefresh} />}
          {status === 'FAILED' && <Badge tone="bad">The briefing failed. See the steps below.</Badge>}
          {run.data?.result ? (
            <>
              <BriefingView b={run.data.result as unknown as Briefing} />
              <div className="flex gap-4 border-t border-slate-100 pt-3 text-xs">
                <button type="button" onClick={() => setInspect(true)} className="font-medium text-brand-700 hover:underline">
                  Inspect what the agent did
                </button>
                <button type="button" onClick={onRefresh} className="text-slate-500 hover:underline">
                  Refresh
                </button>
              </div>
            </>
          ) : (
            <TraceTimeline trace={events} />
          )}
        </div>
      </aside>
      {inspect && runId && <InspectionDrawer runId={runId} onClose={() => setInspect(false)} />}
    </div>
  )
}
