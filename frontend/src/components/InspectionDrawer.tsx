import { AlertTriangle, Bot, CirclePause, CirclePlay, Database, Wrench, X } from 'lucide-react'
import { useEffect, useId, useRef, type ReactNode } from 'react'
import { Link } from 'react-router'
import { useAgentRun, type TraceEvent } from '@/api/agents'
import { CamView, type Cam } from '@/components/CamView'
import { Badge, ErrorState, Loading } from '@/components/ui'
import { AGENT_LABEL, RUN_TONE } from '@/lib/agents'
import { titleCase } from '@/lib/format'


function time(iso: string): string {
  return new Date(iso).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function Json({ value }: { value: unknown }) {
  return (
    <pre className="mt-1 max-h-48 overflow-auto rounded-md bg-slate-50 p-2 text-xs leading-relaxed text-slate-700">
      {JSON.stringify(value, null, 2)}
    </pre>
  )
}

function Step({ icon, title, at, children }: { icon: ReactNode; title: ReactNode; at: string; children?: ReactNode }) {
  return (
    <li className="relative pb-4 pl-8">
      <span className="absolute left-0 top-0.5 grid size-6 place-items-center rounded-full bg-white ring-1 ring-slate-200">{icon}</span>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="font-medium">{title}</span>
        <span className="text-xs tabular-nums text-slate-400">{time(at)}</span>
      </div>
      {children}
    </li>
  )
}

export function TraceTimeline({ trace }: { trace: TraceEvent[] }) {
  if (trace.length === 0) return <p className="text-sm text-slate-500">No steps recorded yet.</p>
  return (
    <ol className="relative border-l border-slate-200 pl-0 text-sm [&>li]:-ml-3">
      {trace.map((e, i) => {
        const key = `${i}-${e.at}`
        switch (e.type) {
          case 'node':
            return (
              <Step key={key} at={e.at} icon={<CirclePlay className="size-3.5 text-brand-600" />} title={<>Step: <code className="text-xs">{String(e.node)}</code></>}>
                <p className="text-xs text-slate-500">{String(e.ms)} ms</p>
              </Step>
            )
          case 'tool':
            return (
              <Step key={key} at={e.at} icon={<Wrench className="size-3.5 text-slate-600" />} title={<>Tool: <code className="text-xs">{String(e.name)}</code></>}>
                <details className="text-xs">
                  <summary className="cursor-pointer text-slate-500">Input and output</summary>
                  <Json value={{ input: e.input, output: e.output }} />
                </details>
              </Step>
            )
          case 'llm':
            return (
              <Step key={key} at={e.at} icon={<Bot className="size-3.5 text-violet-600" />} title={<>Model call ({String(e.provider)})</>}>
                <p className="text-xs text-slate-500">
                  {String(e.model)} · {String(e.input_tokens)} in / {String(e.output_tokens)} out tokens · {String(e.ms)} ms ·{' '}
                  {(e.cited as string[]).length} records cited
                </p>
                {(e.rejected_citations as string[]).length > 0 && (
                  <p className="mt-1 text-xs text-rose-700">Rejected {(e.rejected_citations as string[]).length} citation(s) to records it wasn't given.</p>
                )}
              </Step>
            )
          case 'interrupt':
            return (
              <Step key={key} at={e.at} icon={<CirclePause className="size-3.5 text-amber-600" />} title="Paused for human approval">
                <p className="text-xs text-slate-500">{titleCase(String(e.action))}</p>
              </Step>
            )
          case 'resume':
            return (
              <Step key={key} at={e.at} icon={<CirclePlay className="size-3.5 text-emerald-600" />} title={`Resumed: ${titleCase(String(e.decision))}`} />
            )
          case 'error':
            return (
              <Step key={key} at={e.at} icon={<AlertTriangle className="size-3.5 text-rose-600" />} title={`Stopped: ${String(e.error)}`}>
                <p className="text-xs text-rose-700">{String(e.message)}</p>
              </Step>
            )
          default:
            return <Step key={key} at={e.at} icon={<Database className="size-3.5" />} title={e.type} />
        }
      })}
    </ol>
  )
}

export function InspectionDrawer({ runId, onClose }: { runId: string; onClose: () => void }) {
  const run = useAgentRun(runId)
  const titleId = useId()
  const closeRef = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    closeRef.current?.focus()
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-slate-900/30" onClick={onClose} aria-hidden />
      <aside role="dialog" aria-modal="true" aria-labelledby={titleId} className="relative flex h-full w-full max-w-lg flex-col overflow-y-auto bg-white shadow-xl">
        <div className="flex items-start justify-between gap-3 border-b border-slate-200 p-5">
          <div>
            <h2 id={titleId} className="text-lg font-semibold">Agent run</h2>
            {run.data && (
              <p className="text-sm text-slate-500">
                {AGENT_LABEL[run.data.agent_name] ?? run.data.agent_name}
                {run.data.company_name && ` · ${run.data.company_name}`}
              </p>
            )}
          </div>
          <button ref={closeRef} type="button" onClick={onClose} aria-label="Close" className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100">
            <X className="size-5" aria-hidden />
          </button>
        </div>
        {run.isPending ? (
          <Loading />
        ) : run.isError ? (
          <ErrorState error={run.error} onRetry={() => void run.refetch()} />
        ) : (
          <div className="space-y-6 p-5 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={RUN_TONE[run.data.status]}>{titleCase(run.data.status)}</Badge>
              <span className="text-xs text-slate-500">Started by {run.data.triggered_by_name ?? 'system'} · thread <code>{run.data.thread_id.split(':')[1]?.slice(0, 8)}</code></span>
            </div>
            {run.data.agent_name === 'kyb_intake' && Array.isArray(run.data.result?.discrepancies) && (
              <section>
                <h3 className="mb-2 font-semibold">KYB check outcome</h3>
                {(run.data.result.discrepancies as { detail: string }[]).length === 0 ? (
                  <p className="text-emerald-800">No discrepancies.</p>
                ) : (
                  <ul className="list-disc pl-5">
                    {(run.data.result.discrepancies as { detail: string }[]).map((d) => <li key={d.detail}>{d.detail}</li>)}
                  </ul>
                )}
              </section>
            )}
            {run.data.agent_name === 'cam_draft' && run.data.result && (
              <section>
                <h3 className="mb-2 font-semibold">Draft memo</h3>
                <CamView cam={run.data.result as unknown as Cam} />
              </section>
            )}
            <section>
              <h3 className="mb-2 font-semibold">Records the model used</h3>
              {run.data.cited_records.length === 0 ? (
                <p className="text-slate-500">None cited.</p>
              ) : (
                <ul className="space-y-1">
                  {run.data.cited_records.map((r) => (
                    <li key={r.id} className="flex items-center gap-2">
                      <Badge>{r.kind}</Badge>
                      {r.href ? <Link to={r.href} className="text-brand-700 hover:underline" onClick={onClose}>{r.label}</Link> : <span>{r.label}</span>}
                    </li>
                  ))}
                </ul>
              )}
            </section>
            <section>
              <h3 className="mb-3 font-semibold">Steps</h3>
              <TraceTimeline trace={run.data.trace as TraceEvent[]} />
            </section>
          </div>
        )}
      </aside>
    </div>
  )
}
