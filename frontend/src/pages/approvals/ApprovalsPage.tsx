import { Eye, ShieldCheck, Users } from 'lucide-react'
import { useId, useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { useApprovals, useResolveApproval, type Approval } from '@/api/agents'
import { CamRatios } from '@/components/CamView'
import { gradeTone, type Cam, type CamSection } from '@/lib/cam'
import { InspectionDrawer } from '@/components/InspectionDrawer'
import { RUN_TONE } from '@/lib/agents'
import { Tabs } from '@/components/Tabs'
import { Badge, Card, EmptyState, ErrorState, Loading, PageHeader } from '@/components/ui'
import { formatDate, titleCase } from '@/lib/format'

type Payload = Record<string, unknown>

const ACTION_LABEL: Record<string, string> = {
  CREATE_TASK: 'Create a task',
  SEND_EMAIL: 'Send an email (simulated)',
  ESCALATE_EWS: 'Escalate an early-warning alert',
  SUBMIT_CAM: 'Submit a credit memo',
  FLAG_KYB: 'Flag a KYB issue',
  UPDATE_KYB_RECORD: 'Update a KYB record',
}

const STATUS_TONE = { PENDING: 'warn', APPROVED: 'good', EDITED_AND_APPROVED: 'good', REJECTED: 'bad' } as const

/** Editable fields per action type. Anything not listed is shown read-only. */
const EDITABLE: Record<string, { key: string; label: string; type: 'text' | 'date' | 'textarea' }[]> = {
  CREATE_TASK: [
    { key: 'title', label: 'Task', type: 'text' },
    { key: 'due_date', label: 'Due date', type: 'date' },
  ],
  SEND_EMAIL: [
    { key: 'to_address', label: 'To', type: 'text' },
    { key: 'subject', label: 'Subject', type: 'text' },
    { key: 'body', label: 'Message', type: 'textarea' },
  ],
  ESCALATE_EWS: [
    { key: 'summary', label: 'Note to the credit officer', type: 'textarea' },
    { key: 'rm_task_title', label: 'Call task for the relationship manager', type: 'text' },
  ],
  FLAG_KYB: [{ key: 'reason', label: 'Reason for flagging', type: 'textarea' }],
}

function PayloadEditor({ fields, value, onChange, disabled }: {
  fields: (typeof EDITABLE)[string]
  value: Payload
  onChange: (v: Payload) => void
  disabled: boolean
}) {
  const base = useId()
  return (
    <div className="space-y-3">
      {fields.map((f) => {
        const id = `${base}-${f.key}`
        const common = {
          id,
          disabled,
          value: String(value[f.key] ?? ''),
          className: 'mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm disabled:bg-slate-50 disabled:text-slate-600',
        }
        return (
          <div key={f.key}>
            <label htmlFor={id} className="text-xs text-slate-500">{f.label}</label>
            {f.type === 'textarea' ? (
              <textarea {...common} rows={6} onChange={(e) => onChange({ ...value, [f.key]: e.target.value })} />
            ) : (
              <input {...common} type={f.type} onChange={(e) => onChange({ ...value, [f.key]: e.target.value || null })} />
            )}
          </div>
        )
      })}
    </div>
  )
}

/** Credit memo review: prose and grade are editable; computed ratios are locked. */
function CamEditor({ value, onChange, disabled }: { value: Payload; onChange: (v: Payload) => void; disabled: boolean }) {
  const base = useId()
  const cam = value as unknown as Cam
  const setSection = (i: number, body: string) =>
    onChange({ ...value, sections: cam.sections.map((s: CamSection, j: number) => (j === i ? { ...s, body } : s)) })
  return (
    <div className="space-y-3">
      <CamRatios cam={cam} />
      <div className="flex items-center gap-3">
        <label htmlFor={`${base}-grade`} className="text-xs text-slate-500">Indicative risk grade (1 strongest, 10 weakest)</label>
        <select
          id={`${base}-grade`}
          disabled={disabled}
          value={cam.risk_grade}
          onChange={(e) => onChange({ ...value, risk_grade: Number(e.target.value) })}
          className="rounded-lg border border-slate-300 px-2 py-1 text-sm disabled:bg-slate-50"
        >
          {Array.from({ length: 10 }, (_, i) => i + 1).map((g) => <option key={g} value={g}>{g}</option>)}
        </select>
        <Badge tone={gradeTone(cam.risk_grade)}>Grade {cam.risk_grade}</Badge>
      </div>
      {cam.sections.map((s, i) => (
        <div key={s.key}>
          <label htmlFor={`${base}-${s.key}`} className="text-xs font-medium text-slate-600">{s.title}</label>
          <textarea
            id={`${base}-${s.key}`}
            disabled={disabled}
            rows={4}
            value={s.body}
            onChange={(e) => setSection(i, e.target.value)}
            className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm disabled:bg-slate-50 disabled:text-slate-600"
          />
        </div>
      ))}
    </div>
  )
}

function ApprovalCard({ item, onInspect }: { item: Approval; onInspect: () => void }) {
  const resolve = useResolveApproval(item.id)
  const current = (item.edited_payload ?? item.proposed_payload) as Payload
  const [draft, setDraft] = useState<Payload>(current)
  const [note, setNote] = useState('')
  const [rejecting, setRejecting] = useState(false)
  const pending = item.status === 'PENDING'
  const editable = pending && item.can_review
  const fields = EDITABLE[item.action_type] ?? []
  const edited = JSON.stringify(draft) !== JSON.stringify(item.proposed_payload)

  function approve(e: FormEvent) {
    e.preventDefault()
    resolve.mutate({ decision: 'APPROVE', payload: edited ? draft : null, note: note || null })
  }

  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-semibold">{ACTION_LABEL[item.action_type] ?? titleCase(item.action_type)}</h2>
          <p className="text-sm text-slate-500">
            {item.company_id ? (
              <Link to={`/accounts/${item.company_id}`} className="hover:underline">{item.company_name}</Link>
            ) : 'No account'}{' '}
            · proposed {formatDate(item.created_at)} by an agent for {item.initiator_name ?? 'system'}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {item.four_eyes && <Badge tone="info"><Users className="size-3" aria-hidden /> Four-eyes</Badge>}
          <Badge tone={STATUS_TONE[item.status]}>{titleCase(item.status)}</Badge>
        </div>
      </div>

      {typeof item.proposed_payload.rationale === 'string' && (
        <blockquote className="mt-3 border-l-2 border-violet-200 pl-3 text-sm text-slate-600">
          <span className="text-xs font-medium uppercase tracking-wide text-violet-700">Agent's reasoning</span>
          <p className="mt-0.5">{item.proposed_payload.rationale}</p>
        </blockquote>
      )}

      <form onSubmit={approve} className="mt-4 space-y-3">
        {item.action_type === 'SUBMIT_CAM' ? (
          <CamEditor value={draft} onChange={setDraft} disabled={!editable} />
        ) : fields.length > 0 ? (
          <PayloadEditor fields={fields} value={draft} onChange={setDraft} disabled={!editable} />
        ) : (
          <pre className="overflow-auto rounded-md bg-slate-50 p-2 text-xs">{JSON.stringify(current, null, 2)}</pre>
        )}

        {!pending && (
          <p className="text-sm text-slate-600">
            {titleCase(item.status)} by {item.reviewer_name ?? 'unknown'} on {formatDate(item.resolved_at)}
            {item.review_note && <> — “{item.review_note}”</>}
          </p>
        )}

        {pending && !item.can_review && (
          <p className="flex items-center gap-2 rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-600">
            <ShieldCheck className="size-4 text-slate-400" aria-hidden /> {item.review_blocker}
          </p>
        )}

        {editable && (
          <>
            <div>
              <label htmlFor={`note-${item.id}`} className="text-xs text-slate-500">
                Note {rejecting ? '(required to reject)' : '(optional)'}
              </label>
              <input id={`note-${item.id}`} value={note} onChange={(e) => setNote(e.target.value)} maxLength={2000} className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm" />
            </div>
            {resolve.isError && <p role="alert" className="text-sm text-rose-700">{resolve.error.message}</p>}
            <div className="flex flex-wrap gap-2">
              <button type="submit" disabled={resolve.isPending} className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60">
                {edited ? 'Approve with my edits' : 'Approve'}
              </button>
              <button
                type="button"
                disabled={resolve.isPending}
                onClick={() => {
                  if (!note.trim()) { setRejecting(true); document.getElementById(`note-${item.id}`)?.focus(); return }
                  resolve.mutate({ decision: 'REJECT', note })
                }}
                className="rounded-lg border border-rose-300 px-4 py-2 text-sm font-medium text-rose-700 hover:bg-rose-50 disabled:opacity-60"
              >
                Reject
              </button>
              {edited && (
                <button type="button" onClick={() => setDraft(item.proposed_payload as Payload)} className="px-2 text-sm text-slate-500 underline">
                  Undo edits
                </button>
              )}
            </div>
          </>
        )}
      </form>

      <div className="mt-4 flex items-center justify-between border-t border-slate-100 pt-3 text-xs text-slate-500">
        <span className="flex items-center gap-2">
          Run <Badge tone={RUN_TONE[item.run.status]}>{titleCase(item.run.status)}</Badge>
        </span>
        <button type="button" onClick={onInspect} className="inline-flex items-center gap-1 font-medium text-brand-700 hover:underline">
          <Eye className="size-3.5" aria-hidden /> Inspect what the agent did
        </button>
      </div>
    </Card>
  )
}

export function ApprovalsPage() {
  const [tab, setTab] = useState<'pending' | 'resolved'>('pending')
  const [inspect, setInspect] = useState<string | null>(null)
  const items = useApprovals(tab)

  return (
    <>
      <PageHeader title="Approvals" description="Nothing an agent proposes happens until a person approves it here." />
      <Tabs label="Approval state" active={tab} onChange={setTab} tabs={[{ key: 'pending', label: 'Waiting' }, { key: 'resolved', label: 'Decided' }]} />
      <div className="space-y-4 pt-5">
        {items.isPending ? (
          <Loading />
        ) : items.isError ? (
          <ErrorState error={items.error} onRetry={() => void items.refetch()} />
        ) : items.data.length === 0 ? (
          <Card>
            <EmptyState title={tab === 'pending' ? 'Nothing waiting for approval' : 'No decisions yet'}>
              <p>Agents' proposals land here. In development, try "Suggest a follow-up" on any account.</p>
            </EmptyState>
          </Card>
        ) : (
          items.data.map((item) => <ApprovalCard key={`${item.id}-${item.status}`} item={item} onInspect={() => setInspect(item.run.id)} />)
        )}
      </div>
      {inspect && <InspectionDrawer runId={inspect} onClose={() => setInspect(null)} />}
    </>
  )
}
