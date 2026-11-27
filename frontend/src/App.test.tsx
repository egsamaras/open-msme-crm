import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const RM = { id: 'u1', email: 'rm@demo.local', full_name: 'Layla Rahman', role: 'RM', branch: null }
const RM2 = { id: 'u2', email: 'rm2@demo.local', full_name: 'Yusuf Darwish', role: 'RM', branch: null }
const ACCOUNT = {
  id: 'c1', legal_name: 'Falcon Light Steel Fabrication LLC', trading_name: 'Falcon Steel',
  cr_number: 'AE-123', country: 'AE', industry: 'Manufacturing', tier: 'MEDIUM', currency: 'AED',
  annual_turnover: '30000000.00', risk_rating: 7, kyb_status: 'VERIFIED', kyb_next_review: null,
  rm_name: 'Layla Rahman', total_limit: '1000000.00', total_utilized: '950000.00', open_ews: 0,
}

/** Stands in for the browser's EventSource: the test sends the run's events and sees it closed. */
class FakeEventSource extends EventTarget {
  static opened: FakeEventSource[] = []
  closed = false
  constructor() {
    super()
    FakeEventSource.opened.push(this)
  }
  close() {
    this.closed = true
  }
}

function renderApp(routes: Record<string, () => Response | Promise<Response>>) {
  vi.stubGlobal('fetch', vi.fn(async (input: Request) => {
    const path = new URL(input.url).pathname
    const handler = routes[`${input.method} ${path}`]
    return handler ? handler() : json(404, { detail: 'not mocked' })
  }))
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}><App /></QueryClientProvider>)
}

afterEach(() => {
  vi.unstubAllGlobals()
  window.history.replaceState(null, '', '/')
})

describe('App', () => {
  it('shows the sign-in form when signed out, and signs in', async () => {
    let signedIn = false
    renderApp({
      'GET /api/auth/session': () => json(200, { user: signedIn ? RM : null }),
      'GET /api/info': () => json(200, { environment: 'test', llm_provider: 'mock', dev_persona_switch: false, default_currency: 'BHD' }),
      'POST /api/auth/login': () => { signedIn = true; return json(200, RM) },
      'GET /api/accounts': () => json(200, [ACCOUNT]),
    })
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText('Password'), 'demo1234')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByText('Good day, Layla')).toBeInTheDocument()
    expect(screen.getByText('AI: mock mode')).toBeInTheDocument()
    expect(await screen.findByText('Across 1 GCC market')).toBeInTheDocument()
    // Compliance-only navigation is hidden for an RM.
    expect(screen.queryByRole('link', { name: /audit trail/i })).not.toBeInTheDocument()
  })

  it('shows none of the previous persona\'s rows after "View as" switches', async () => {
    let who = RM
    window.history.replaceState(null, '', '/accounts')
    renderApp({
      'GET /api/auth/session': () => json(200, { user: who }),
      'GET /api/info': () => json(200, { environment: 'test', llm_provider: 'mock', dev_persona_switch: true, default_currency: 'BHD' }),
      'GET /api/auth/personas': () => json(200, [RM, RM2]),
      'POST /api/auth/dev-switch': () => { who = RM2; return json(200, RM2) },
      // Yusuf's list never arrives, so any row on screen after the switch is left over from Layla.
      'GET /api/accounts': () => (who === RM ? json(200, [ACCOUNT]) : new Promise<Response>(() => {})),
    })
    expect(await screen.findByRole('link', { name: 'Falcon Steel' })).toBeInTheDocument()

    await userEvent.setup().selectOptions(await screen.findByLabelText('View as'), RM2.id)
    expect(await screen.findByText('Yusuf Darwish')).toBeInTheDocument()
    expect(screen.getByText('Loading accounts…')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Falcon Steel' })).not.toBeInTheDocument()
  })

  it('drops the previous persona\'s scan steps, and closes its stream, after "View as" switches', async () => {
    let who = RM
    FakeEventSource.opened = []
    vi.stubGlobal('EventSource', FakeEventSource)
    window.history.replaceState(null, '', '/risk')
    renderApp({
      'GET /api/auth/session': () => json(200, { user: who }),
      'GET /api/info': () => json(200, { environment: 'test', llm_provider: 'mock', dev_persona_switch: true, default_currency: 'BHD' }),
      'GET /api/auth/personas': () => json(200, [RM, RM2]),
      'POST /api/auth/dev-switch': () => { who = RM2; return json(200, RM2) },
      'GET /api/ews': () => json(200, []),
      'POST /api/agents/ews-scan': () => json(202, { id: 'run1', status: 'RUNNING' }),
    })
    const user = userEvent.setup()
    // The Risk radar page loads on demand, so give it time on a slow machine.
    await user.click(await screen.findByRole('button', { name: 'Run portfolio scan' }, { timeout: 5000 }))
    await vi.waitFor(() => expect(FakeEventSource.opened).toHaveLength(1))
    const stream = FakeEventSource.opened[0]!
    act(() => {
      const step = { type: 'node', node: 'scan_portfolio', ms: 12, at: '2026-11-26T10:00:00Z' }
      stream.dispatchEvent(new MessageEvent('trace', { data: JSON.stringify(step) }))
    })
    expect(await screen.findByText('scan_portfolio')).toBeInTheDocument()

    await user.selectOptions(await screen.findByLabelText('View as'), RM2.id)
    expect(await screen.findByText('Yusuf Darwish')).toBeInTheDocument()
    expect(screen.queryByText('scan_portfolio')).not.toBeInTheDocument()
    expect(stream.closed).toBe(true)
  })

  it('shows a wrong-password message', async () => {
    renderApp({
      'GET /api/auth/session': () => json(200, { user: null }),
      'GET /api/info': () => json(200, { environment: 'test', llm_provider: 'mock', dev_persona_switch: false, default_currency: 'BHD' }),
      'POST /api/auth/login': () => json(401, { detail: 'Wrong email or password' }),
    })
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText('Password'), 'nope')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Wrong email or password')
  })
})
