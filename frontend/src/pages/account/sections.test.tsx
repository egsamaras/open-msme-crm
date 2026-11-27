import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AccountDetail } from '@/api/queries'
import { meKey } from '@/auth'
import { inDays, inTimezone, shown } from '@/test/dates'
import { DocumentsTab } from './sections'

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const ACCOUNT: AccountDetail = {
  id: 'c1', legal_name: 'Falcon Light Steel Fabrication LLC', trading_name: 'Falcon Steel', cr_number: 'AE-123',
  country: 'AE', industry: 'Manufacturing', tier: 'MEDIUM', annual_turnover: '30000000.00', currency: 'AED',
  risk_rating: 7, kyb_status: 'VERIFIED', kyb_next_review: null, rm_id: 'u1', rm_name: 'Layla Rahman',
  ubo_threshold_pct: '25.00', owners: [], contacts: [],
}

function doc(fileName: string, expiryDate: string) {
  return {
    id: fileName, deal_id: null, doc_type: 'TRADE_LICENSE', file_name: fileName, expiry_date: expiryDate,
    verification_status: 'VERIFIED', created_at: '2026-01-05T09:00:00Z', has_text: false,
    check_run_id: null, check_run_status: null,
  }
}

function renderTab(docs: unknown[]) {
  vi.stubGlobal('fetch', vi.fn(async (req: Request) =>
    new URL(req.url).pathname === `/api/accounts/${ACCOUNT.id}/documents` ? json(200, docs) : json(404, { detail: 'not mocked' }),
  ))
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  // A credit officer reads documents but doesn't upload them, so there's no upload form.
  qc.setQueryData(meKey, { id: 'u3', email: 'credit@demo.local', full_name: 'Test User', role: 'CREDIT_OFFICER', branch: null })
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <DocumentsTab account={ACCOUNT} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

/** A document's row, found by its file name. */
const item = (fileName: string) => screen.getByText(new RegExp(`^${fileName} · expires`)).closest('li')!

afterEach(() => {
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
})

describe('DocumentsTab', () => {
  it('words an expiry as the accounts list does, next to the date as written, even west of UTC', async () => {
    inTimezone('America/New_York')
    renderTab([doc('lapsed.pdf', inDays(-1)), doc('today.pdf', inDays(0)), doc('tomorrow.pdf', inDays(1)), doc('later.pdf', inDays(31))])
    expect(await screen.findByText(`today.pdf · expires ${shown(0)}`)).toBeInTheDocument()
    expect(within(item('lapsed.pdf')).getByText('Expired')).toBeInTheDocument()
    expect(within(item('today.pdf')).getByText('Expires today')).toBeInTheDocument()
    expect(within(item('tomorrow.pdf')).getByText('1 day left')).toBeInTheDocument()
    expect(item('later.pdf')).not.toHaveTextContent(/Expired|Expires today|left/)
    // The same colours as the accounts list: rose once expired, amber until then.
    expect(within(item('lapsed.pdf')).getByText('Expired')).toHaveClass('bg-rose-50')
    expect(within(item('today.pdf')).getByText('Expires today')).toHaveClass('bg-amber-50')
    expect(within(item('tomorrow.pdf')).getByText('1 day left')).toHaveClass('bg-amber-50')
  })
})
