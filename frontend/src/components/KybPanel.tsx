import { ShieldCheck } from 'lucide-react'
import { useEffect, useId, useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { useQueryClient } from '@tanstack/react-query'
import { useAgentRun, useRunStream } from '@/api/agents'
import { useCheckDocument, useUploadDocument, type DocType } from '@/api/kyb'
import { TraceTimeline } from '@/components/InspectionDrawer'
import { Badge } from '@/components/ui'
import { DOC_LABEL } from '@/lib/format'

export const KYB_ROLES = new Set(['RM', 'COMPLIANCE', 'ADMIN'])

type KybResult = { outcome: string; discrepancies?: { kind: string; detail: string }[]; notes?: string[] }

/** Live progress and outcome of one KYB check. */
function CheckProgress({ runId, companyId }: { runId: string; companyId: string }) {
  const qc = useQueryClient()
  const { events, status } = useRunStream(runId)
  const done = status !== 'RUNNING'
  const run = useAgentRun(done ? runId : null)
  const result = run.data?.result as KybResult | null | undefined

  useEffect(() => {
    if (done) void qc.invalidateQueries({ queryKey: ['accounts', companyId] })
  }, [done, qc, companyId])

  return (
    <div className="mt-3 space-y-2 rounded-lg border border-slate-200 p-3" aria-live="polite">
      <TraceTimeline trace={events} />
      {status === 'FAILED' && <Badge tone="bad">Check failed</Badge>}
      {result?.outcome === 'verified' && (
        <p className="text-emerald-800">Verified: nothing disagrees with the bank's records.{result.notes?.length ? ` Note: ${result.notes.join('; ')}.` : ''}</p>
      )}
      {status === 'AWAITING_APPROVAL' && result && (
        <div className="text-amber-900">
          <p className="font-medium">Discrepancies found. A compliance officer must review before anything changes.</p>
          <ul className="mt-1 list-disc pl-5">{result.discrepancies?.map((d) => <li key={d.detail}>{d.detail}</li>)}</ul>
          <Link to="/approvals" className="underline">Open Approvals</Link>
        </div>
      )}
    </div>
  )
}

export function CheckButton({ companyId, documentId }: { companyId: string; documentId: string }) {
  const check = useCheckDocument(companyId)
  return (
    <div>
      <button
        type="button"
        disabled={check.isPending || !!check.data}
        onClick={() => check.mutate(documentId)}
        className="inline-flex items-center gap-1 rounded-lg border border-slate-300 px-2 py-0.5 text-xs hover:bg-slate-50 disabled:opacity-60"
      >
        <ShieldCheck className="size-3.5" aria-hidden /> Run KYB check
      </button>
      {check.isError && <p role="alert" className="mt-1 text-xs text-rose-700">{check.error.message}</p>}
      {check.data && <CheckProgress runId={check.data.id} companyId={companyId} />}
    </div>
  )
}

const DOC_TYPES = Object.keys(DOC_LABEL) as DocType[]

export function UploadForm({ companyId }: { companyId: string }) {
  const id = useId()
  const upload = useUploadDocument(companyId)
  const [docType, setDocType] = useState<DocType>('UBO_DECLARATION')
  const [file, setFile] = useState<File | null>(null)

  function submit(e: FormEvent) {
    e.preventDefault()
    if (file) upload.mutate({ docType, file })
  }

  return (
    <form onSubmit={submit} className="mt-4 space-y-2 border-t border-slate-100 pt-4 text-sm">
      <p className="font-medium">Upload a document for a KYB check</p>
      <p className="text-xs text-slate-500">.txt, .json or .pdf, up to 1 MB. Its text is treated as data: instructions inside it are ignored.</p>
      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor={`${id}-type`} className="sr-only">Document type</label>
        <select id={`${id}-type`} value={docType} onChange={(e) => setDocType(e.target.value as DocType)} className="rounded-lg border border-slate-300 px-2 py-1.5">
          {DOC_TYPES.map((t) => <option key={t} value={t}>{DOC_LABEL[t]}</option>)}
        </select>
        <label htmlFor={`${id}-file`} className="sr-only">File</label>
        <input id={`${id}-file`} type="file" accept=".txt,.json,.pdf" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="text-xs" />
        <button type="submit" disabled={!file || upload.isPending} className="rounded-lg bg-brand-600 px-3 py-1.5 font-medium text-white hover:bg-brand-700 disabled:opacity-60">
          Upload and check
        </button>
      </div>
      {upload.isError && <p role="alert" className="text-rose-700">{upload.error.message}</p>}
      {upload.data && <CheckProgress runId={upload.data.id} companyId={companyId} />}
    </form>
  )
}
