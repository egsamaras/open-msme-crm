import { KanbanSquare, Table2 } from 'lucide-react'
import { useState } from 'react'
import { useDeals, type Deal, type DealStage } from '@/api/queries'
import { Badge, Card, EmptyState, ErrorState, Loading, PageHeader } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatDate, formatMoney, PRODUCT_LABEL, STAGE_LABEL } from '@/lib/format'
import { DealDrawer } from './DealDrawer'

const BOARD: DealStage[] = ['LEAD', 'QUALIFICATION', 'DOC_COLLECTION', 'CREDIT_UNDERWRITING', 'APPROVAL', 'DISBURSED']

function DealCard({ deal, onOpen }: { deal: Deal; onOpen: () => void }) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className="w-full rounded-lg border border-slate-200 bg-white p-3 text-left text-sm shadow-sm transition hover:border-brand-500 hover:shadow"
    >
      <div className="font-medium">{deal.company_name}</div>
      <div className="text-xs text-slate-500">{PRODUCT_LABEL[deal.product]}</div>
      <div className="mt-2 flex items-center justify-between gap-2">
        <span className="tabular-nums">{formatMoney(deal.requested_amount, deal.currency, true)}</span>
        <span className="text-xs text-slate-500">{deal.probability_pct}%</span>
      </div>
      <div className="mt-1 text-xs text-slate-500">Close {formatDate(deal.expected_close)}</div>
    </button>
  )
}

function Board({ deals, onOpen }: { deals: Deal[]; onOpen: (id: string) => void }) {
  return (
    <div className="flex gap-3 overflow-x-auto pb-2">
      {BOARD.map((stage) => {
        const col = deals.filter((d) => d.stage === stage)
        return (
          <section key={stage} aria-label={STAGE_LABEL[stage]} className="w-60 shrink-0 rounded-xl bg-slate-100 p-2">
            <h2 className="flex items-center justify-between px-1 pb-2 text-xs font-semibold uppercase tracking-wide text-slate-600">
              {STAGE_LABEL[stage]}
              <span className="rounded-full bg-white px-2 py-0.5 text-slate-500">{col.length}</span>
            </h2>
            <div className="space-y-2">
              {col.length === 0 ? (
                <p className="px-1 py-4 text-center text-xs text-slate-400">Empty</p>
              ) : (
                col.map((d) => <DealCard key={d.id} deal={d} onOpen={() => onOpen(d.id)} />)
              )}
            </div>
          </section>
        )
      })}
    </div>
  )
}

function DealTable({ deals, onOpen }: { deals: Deal[]; onOpen: (id: string) => void }) {
  return (
    <Card className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
          <tr>
            <th className="px-3 py-3 font-medium">Company</th>
            <th className="px-3 py-3 font-medium">Product</th>
            <th className="px-3 py-3 font-medium">Stage</th>
            <th className="px-3 py-3 text-right font-medium">Requested</th>
            <th className="px-3 py-3 text-right font-medium">Prob.</th>
            <th className="px-3 py-3 font-medium">Close</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {deals.map((d) => (
            <tr key={d.id} className="cursor-pointer hover:bg-slate-50" onClick={() => onOpen(d.id)}>
              <td className="px-3 py-3">
                <button type="button" className="font-medium hover:underline" onClick={() => onOpen(d.id)}>
                  {d.company_name}
                </button>
              </td>
              <td className="px-3 py-3">{PRODUCT_LABEL[d.product]}</td>
              <td className="px-3 py-3">
                <Badge tone={d.stage === 'LOST' ? 'bad' : d.stage === 'DISBURSED' ? 'good' : 'info'}>{STAGE_LABEL[d.stage]}</Badge>
              </td>
              <td className="whitespace-nowrap px-3 py-3 text-right tabular-nums">{formatMoney(d.requested_amount, d.currency)}</td>
              <td className="px-3 py-3 text-right tabular-nums">{d.probability_pct}%</td>
              <td className="whitespace-nowrap px-3 py-3">{formatDate(d.expected_close)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  )
}

export function PipelinePage() {
  const [view, setView] = useState<'board' | 'table'>('board')
  const [openId, setOpenId] = useState<string | null>(null)
  const deals = useDeals()

  const toggle = (
    <div role="group" aria-label="View" className="inline-flex rounded-lg border border-slate-300 bg-white p-0.5 text-sm">
      {([['board', 'Board', KanbanSquare], ['table', 'Table', Table2]] as const).map(([key, label, Icon]) => (
        <button
          key={key}
          type="button"
          aria-pressed={view === key}
          onClick={() => setView(key)}
          className={cn('inline-flex items-center gap-1.5 rounded-md px-3 py-1.5', view === key ? 'bg-brand-600 text-white' : 'text-slate-600 hover:bg-slate-100')}
        >
          <Icon className="size-4" aria-hidden /> {label}
        </button>
      ))}
    </div>
  )

  const lost = deals.data?.filter((d) => d.stage === 'LOST').length ?? 0
  return (
    <>
      <PageHeader
        title="Pipeline"
        description={`Origination from lead to disbursement.${lost ? ` ${lost} lost ${lost === 1 ? 'deal is' : 'deals are'} in the table view.` : ''}`}
        actions={toggle}
      />
      {deals.isPending ? (
        <Loading label="Loading pipeline…" />
      ) : deals.isError ? (
        <ErrorState error={deals.error} onRetry={() => void deals.refetch()} />
      ) : deals.data.length === 0 ? (
        <Card><EmptyState title="No deals yet" /></Card>
      ) : view === 'board' ? (
        <Board deals={deals.data} onOpen={setOpenId} />
      ) : (
        <DealTable deals={deals.data} onOpen={setOpenId} />
      )}
      {openId && <DealDrawer dealId={openId} onClose={() => setOpenId(null)} />}
    </>
  )
}
