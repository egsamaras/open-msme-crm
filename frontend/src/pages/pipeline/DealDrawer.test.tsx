import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { DealDrawer } from './DealDrawer'

const DEAL = {
  id: 'd1', company_id: 'c1', company_name: 'Falcon Steel', currency: 'AED', title: 'Falcon — LC',
  product: 'TRADE_FINANCE_LC', stage: 'DOC_COLLECTION', requested_amount: '5141500.00', probability_pct: 40,
  expected_close: '2026-12-02', owner_name: 'Layla Rahman', has_draft_cam: false,
  checklist: [
    { doc_type: 'TRADE_LICENSE', state: 'VERIFIED', document_id: 'x', expiry_date: '2028-04-08' },
    { doc_type: 'FINANCIAL_STATEMENT', state: 'MISSING', document_id: null, expiry_date: null },
  ],
  checklist_complete: false,
  allowed_stages: ['LEAD', 'QUALIFICATION', 'CREDIT_UNDERWRITING', 'LOST'],
}

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

afterEach(() => vi.unstubAllGlobals())

describe('DealDrawer', () => {
  it('shows the checklist and the server refusal for a stage move', async () => {
    vi.stubGlobal('fetch', vi.fn(async (req: Request) =>
      req.method === 'PATCH'
        ? json(409, { detail: "Can't move a deal from DOC_COLLECTION to LOST by hand" })
        : json(200, DEAL),
    ))
    const onClose = vi.fn()
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter>
          <DealDrawer dealId="d1" onClose={onClose} />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(await screen.findByRole('dialog', { name: 'Falcon Steel' })).toBeInTheDocument()
    expect(screen.getByText('Incomplete')).toBeInTheDocument()
    expect(screen.getByText('Financial statements')).toBeInTheDocument()
    // Approval is not offered: it's reached through the four-eyes credit memo flow.
    expect(screen.queryByRole('option', { name: 'Approval' })).not.toBeInTheDocument()

    const user = userEvent.setup()
    await user.selectOptions(screen.getByLabelText('Move to stage'), 'LOST')
    await user.click(screen.getByRole('button', { name: 'Move' }))
    expect(await screen.findByRole('alert')).toHaveTextContent("Can't move a deal")

    await user.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalled()
  })
})
