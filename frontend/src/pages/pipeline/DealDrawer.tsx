import { CheckCircle2, CircleAlert, CircleDashed, X } from 'lucide-react'
import { useEffect, useId, useRef, useState } from 'react'
import { Link } from 'react-router'
import { useDeal, useUpdateDeal, type DealDetail, type DealStage } from '@/api/queries'
import { CamPanel } from '@/components/CamPanel'
import { Badge, ErrorState, Loading } from '@/components/ui'
import { DOC_LABEL, formatDate, formatMoney, PRODUCT_LABEL, STAGE_LABEL } from '@/lib/format'

const STATE_ICON = {
  VERIFIED: <CheckCircle2 className="size-4 text-emerald-600" aria-hidden />,
  PENDING: <CircleDashed className="size-4 text-amber-600" aria-hidden />,
  MISSING: <CircleAlert className="size-4 text-rose-600" aria-hidden />,
  EXPIRED: <CircleAlert className="size-4 text-rose-600" aria-hidden />,
  REJECTED: <CircleAlert className="size-4 text-rose-600" aria-hidden />,
} as const

function StageMover({ deal }: { deal: DealDetail }) {
  const id = useId()
  const update = useUpdateDeal(deal.id)
  const [target, setTarget] = useState<DealStage | ''>('')
  if (deal.allowed_stages.length === 0) {
    return <p className="text-sm text-slate-500">You can't move this deal from {STAGE_LABEL[deal.stage]}.</p>
  }
  return (
    <div className="space-y-2">
      <div className="flex gap-2">
        <label htmlFor={id} className="sr-only">Move to stage</label>
        <select id={id} value={target} onChange={(e) => setTarget(e.target.value as DealStage)} className="flex-1 rounded-lg border border-slate-300 px-2 py-1.5 text-sm">
          <option value="">Move to…</option>
          {deal.allowed_stages.map((s) => <option key={s} value={s}>{STAGE_LABEL[s]}</option>)}
        </select>
        <button
          type="button"
          disabled={!target || update.isPending}
          onClick={() => target && update.mutate({ stage: target }, { onSuccess: () => setTarget('') })}
          className="rounded-lg bg-brand-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
        >
          Move
        </button>
      </div>
      {update.isError && <p role="alert" className="text-sm text-rose-700">{update.error.message}</p>}
    </div>
  )
}

export function DealDrawer({ dealId, onClose }: { dealId: string; onClose: () => void }) {
  const deal = useDeal(dealId)
  const titleId = useId()
  const closeRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    closeRef.current?.focus()
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <div className="absolute inset-0 bg-slate-900/30" onClick={onClose} aria-hidden />
      <aside role="dialog" aria-modal="true" aria-labelledby={titleId} className="relative flex h-full w-full max-w-md flex-col overflow-y-auto bg-white shadow-xl">
        <div className="flex items-start justify-between gap-3 border-b border-slate-200 p-5">
          <div>
            <h2 id={titleId} className="text-lg font-semibold">{deal.data?.company_name ?? 'Deal'}</h2>
            {deal.data && <p className="text-sm text-slate-500">{PRODUCT_LABEL[deal.data.product]}</p>}
          </div>
          <button ref={closeRef} type="button" onClick={onClose} aria-label="Close" className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100">
            <X className="size-5" aria-hidden />
          </button>
        </div>
        {deal.isPending ? (
          <Loading />
        ) : deal.isError ? (
          <ErrorState error={deal.error} onRetry={() => void deal.refetch()} />
        ) : (
          <div className="space-y-6 p-5 text-sm">
            <dl className="grid grid-cols-2 gap-4">
              <div>
                <dt className="text-xs text-slate-500">Requested</dt>
                <dd className="text-base font-semibold tabular-nums">{formatMoney(deal.data.requested_amount, deal.data.currency)}</dd>
              </div>
              <div>
                <dt className="text-xs text-slate-500">Stage</dt>
                <dd><Badge tone="info">{STAGE_LABEL[deal.data.stage]}</Badge></dd>
              </div>
              <div>
                <dt className="text-xs text-slate-500">Probability</dt>
                <dd className="tabular-nums">{deal.data.probability_pct}%</dd>
              </div>
              <div>
                <dt className="text-xs text-slate-500">Expected close</dt>
                <dd>{formatDate(deal.data.expected_close)}</dd>
              </div>
              <div className="col-span-2">
                <dt className="text-xs text-slate-500">Owner</dt>
                <dd>{deal.data.owner_name ?? '—'}</dd>
              </div>
            </dl>

            <section>
              <h3 className="mb-2 font-semibold">Move stage</h3>
              <StageMover deal={deal.data} />
              {deal.data.stage === 'CREDIT_UNDERWRITING' && (
                <p className="mt-2 text-xs text-slate-500">Approval is reached by submitting a credit memo for four-eyes review, not by hand.</p>
              )}
            </section>

            <section>
              <div className="mb-2 flex items-center justify-between">
                <h3 className="font-semibold">Document checklist</h3>
                {deal.data.checklist_complete ? <Badge tone="good">Complete</Badge> : <Badge tone="warn">Incomplete</Badge>}
              </div>
              <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200">
                {deal.data.checklist.map((c) => (
                  <li key={c.doc_type} className="flex items-center justify-between gap-2 px-3 py-2">
                    <span className="flex items-center gap-2">
                      {STATE_ICON[c.state]}
                      {DOC_LABEL[c.doc_type]}
                    </span>
                    <span className="text-xs text-slate-500">
                      {c.state.charAt(0) + c.state.slice(1).toLowerCase()}
                      {c.expiry_date && ` · exp. ${formatDate(c.expiry_date)}`}
                    </span>
                  </li>
                ))}
              </ul>
            </section>

            <CamPanel deal={deal.data} />

            <Link to={`/accounts/${deal.data.company_id}`} className="inline-block text-brand-700 underline" onClick={onClose}>
              Open account
            </Link>
          </div>
        )}
      </aside>
    </div>
  )
}
