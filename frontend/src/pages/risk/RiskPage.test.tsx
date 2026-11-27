import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { meKey } from '@/auth'
import { RiskPage } from './RiskPage'

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function renderPage(role: string) {
  vi.stubGlobal('fetch', vi.fn(async (req: Request) =>
    new URL(req.url).pathname === '/api/ews' ? json(200, []) : json(404, { detail: 'not mocked' }),
  ))
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  qc.setQueryData(meKey, { id: 'u1', email: 'u1@demo.local', full_name: 'Test User', role, branch: null })
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <RiskPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => vi.unstubAllGlobals())

describe('RiskPage', () => {
  it('asks only roles that can scan to run a scan', async () => {
    renderPage('COMPLIANCE')
    expect(await screen.findByText('No open alerts')).toBeInTheDocument()
    expect(screen.queryByText(/Run a portfolio scan/)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Run portfolio scan' })).not.toBeInTheDocument()
  })

  it('asks an RM to scan, and says each review waits for approval (not "your" approval)', async () => {
    renderPage('RM')
    expect(await screen.findByText('Run a portfolio scan to check accounts against the rules.')).toBeInTheDocument()
    expect(screen.getByText(/gets its own agent review, which waits for approval\./)).toBeInTheDocument()
  })
})
