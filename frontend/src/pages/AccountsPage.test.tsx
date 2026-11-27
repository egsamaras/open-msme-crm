import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { meKey } from '@/auth'
import { inDays, inTimezone, shown } from '@/test/dates'
import { AccountsPage } from './AccountsPage'

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function account(name: string, nextDocExpiry: string | null = null) {
  return {
    id: name, legal_name: `${name} LLC`, trading_name: name, cr_number: 'AE-123', country: 'AE',
    industry: 'Manufacturing', tier: 'SMALL', currency: 'AED', annual_turnover: '3000000.00',
    risk_rating: 3, kyb_status: 'VERIFIED', kyb_next_review: null, rm_name: 'Layla Rahman',
    total_limit: '100000.00', total_utilized: '50000.00', open_ews: 0, next_doc_expiry: nextDocExpiry,
  }
}

function renderPage(role: string, rows: unknown[]) {
  vi.stubGlobal('fetch', vi.fn(async (req: Request) =>
    new URL(req.url).pathname === '/api/accounts' ? json(200, rows) : json(404, { detail: 'not mocked' }),
  ))
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  // Signed in before the page renders, so the role is known when the rows arrive.
  qc.setQueryData(meKey, { id: 'u1', email: 'u1@demo.local', full_name: 'Test User', role, branch: null })
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AccountsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const row = (name: string) => screen.getByRole('row', { name: new RegExp(name) })

afterEach(() => {
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
})

describe('AccountsPage', () => {
  it('tells an RM with no accounts that none are assigned, and only a search that nothing matched', async () => {
    renderPage('RM', [])
    expect(await screen.findByText('No accounts are assigned to you yet')).toBeInTheDocument()
    expect(screen.queryByText('No accounts match')).not.toBeInTheDocument()

    await userEvent.setup().type(screen.getByLabelText('Search accounts'), 'pearl')
    expect(await screen.findByText('No accounts match')).toBeInTheDocument()
  })

  it.each(['CREDIT_OFFICER', 'COMPLIANCE', 'ADMIN'])('tells %s, who sees the whole bank, that there are no accounts yet', async (role) => {
    renderPage(role, [])
    expect(await screen.findByText('No accounts yet')).toBeInTheDocument()
    expect(screen.queryByText('No accounts are assigned to you yet')).not.toBeInTheDocument()
  })

  it('counts a single account in the singular', async () => {
    renderPage('RM', [account('Falcon Steel')])
    expect(await screen.findByText(/assigned to you\. 1 account\. Amounts/)).toBeInTheDocument()
  })

  it('tells compliance that the list goes by KYB status, then trade licence or CR certificate expiry', async () => {
    renderPage('COMPLIANCE', [account('Falcon Steel')])
    expect(
      await screen.findByText(/^Every account in the bank, KYB issues first, then the soonest trade licence or CR certificate expiry\./),
    ).toBeInTheDocument()
  })

  it('says in words, not only in colour, when a document has expired or expires soon', async () => {
    renderPage('COMPLIANCE', [
      account('Yesterday Co', inDays(-1)),
      account('Today Co', inDays(0)),
      account('Tomorrow Co', inDays(1)),
      account('Month Co', inDays(30)),
      account('Month And A Day Co', inDays(31)),
      account('Undated Co'),
    ])
    await screen.findByText('Today Co')
    expect(row('Yesterday Co')).toHaveTextContent('Expired')
    expect(row('Today Co')).toHaveTextContent('Expires today')
    expect(row('Tomorrow Co')).toHaveTextContent('1 day left')
    expect(row('Month Co')).toHaveTextContent('30 days left')
    expect(row('Month And A Day Co')).not.toHaveTextContent(/Expire|left/)
    expect(row('Undated Co')).not.toHaveTextContent(/Expire|left/)
    // Expired is red; a document that expires today is still valid, so amber.
    expect(within(row('Yesterday Co')).getByText('Expired')).toHaveClass('bg-rose-50')
    expect(within(row('Today Co')).getByText('Expires today')).toHaveClass('bg-amber-50')
  })

  it('shows the same day in the date and in the words, even west of UTC', async () => {
    inTimezone('America/New_York')
    renderPage('COMPLIANCE', [account('Today Co', inDays(0)), account('Tomorrow Co', inDays(1))])
    await screen.findByText('Today Co')
    expect(within(row('Today Co')).getByText(shown(0))).toBeInTheDocument()
    expect(within(row('Today Co')).getByText('Expires today')).toBeInTheDocument()
    expect(within(row('Tomorrow Co')).getByText(shown(1))).toBeInTheDocument()
    expect(within(row('Tomorrow Co')).getByText('1 day left')).toBeInTheDocument()
  })
})
