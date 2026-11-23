import { ArrowLeft } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { useAccount, useDocuments, useInteractions } from '@/api/queries'
import { BriefingButton } from '@/components/BriefingPanel'
import { Tabs } from '@/components/Tabs'
import { Badge, ErrorState, Loading } from '@/components/ui'
import { formatDate, formatMoney, titleCase } from '@/lib/format'
import { DocumentsTab, EwsTab, FacilitiesTab, FinancialsTab, InteractionsTab, OverviewTab } from './sections'

type TabKey = 'overview' | 'facilities' | 'financials' | 'documents' | 'interactions' | 'ews'

const KYB_TONE = { VERIFIED: 'good', PENDING_RENEWAL: 'warn', FLAGGED: 'bad' } as const

export function AccountPage() {
  const { id = '' } = useParams()
  const [tab, setTab] = useState<TabKey>('overview')
  const account = useAccount(id)
  const docs = useDocuments(id)
  const interactions = useInteractions(id)

  if (account.isPending) return <Loading label="Loading account…" />
  if (account.isError) return <ErrorState error={account.error} onRetry={() => void account.refetch()} />
  const a = account.data

  return (
    <>
      <Link to="/accounts" className="mb-3 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-800">
        <ArrowLeft className="size-4" aria-hidden /> Accounts
      </Link>
      <div className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{a.trading_name ?? a.legal_name}</h1>
          <p className="mt-1 text-sm text-slate-500">
            {a.legal_name} · CR {a.cr_number} · {a.industry}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="neutral">{titleCase(a.tier)}</Badge>
          <Badge tone={a.risk_rating >= 7 ? 'bad' : a.risk_rating >= 5 ? 'warn' : 'good'}>Risk {a.risk_rating}/10</Badge>
          <Badge tone={KYB_TONE[a.kyb_status]}>KYB {titleCase(a.kyb_status).toLowerCase()}</Badge>
          <BriefingButton companyId={a.id} companyName={a.trading_name ?? a.legal_name} />
        </div>
      </div>
      <dl className="mb-6 grid grid-cols-2 gap-x-6 gap-y-3 text-sm sm:grid-cols-4">
        <div>
          <dt className="text-xs text-slate-500">Annual turnover</dt>
          <dd className="font-medium tabular-nums">{formatMoney(a.annual_turnover, a.currency)}</dd>
        </div>
        <div>
          <dt className="text-xs text-slate-500">Country</dt>
          <dd className="font-medium">{a.country}</dd>
        </div>
        <div>
          <dt className="text-xs text-slate-500">Relationship manager</dt>
          <dd className="font-medium">{a.rm_name ?? '—'}</dd>
        </div>
        <div>
          <dt className="text-xs text-slate-500">Next KYB review</dt>
          <dd className="font-medium">{formatDate(a.kyb_next_review)}</dd>
        </div>
      </dl>

      <Tabs
        label="Account sections"
        active={tab}
        onChange={setTab}
        tabs={[
          { key: 'overview', label: 'Overview' },
          { key: 'facilities', label: 'Facilities' },
          { key: 'financials', label: 'Financials' },
          { key: 'documents', label: 'Owners & documents', count: docs.data?.length },
          { key: 'interactions', label: 'Interactions', count: interactions.data?.length },
          { key: 'ews', label: 'Alerts' },
        ]}
      />
      <div role="tabpanel" className="pt-5">
        {tab === 'overview' && <OverviewTab account={a} />}
        {tab === 'facilities' && <FacilitiesTab account={a} />}
        {tab === 'financials' && <FinancialsTab account={a} />}
        {tab === 'documents' && <DocumentsTab account={a} />}
        {tab === 'interactions' && <InteractionsTab account={a} />}
        {tab === 'ews' && <EwsTab account={a} />}
      </div>
    </>
  )
}
