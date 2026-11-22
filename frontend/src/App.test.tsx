import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const RM = { id: 'u1', email: 'rm@demo.local', full_name: 'Layla Rahman', role: 'RM', branch: null }
const ACCOUNT = {
  id: 'c1', legal_name: 'Falcon Light Steel Fabrication LLC', trading_name: 'Falcon Steel',
  cr_number: 'AE-123', country: 'AE', industry: 'Manufacturing', tier: 'MEDIUM', currency: 'AED',
  annual_turnover: '30000000.00', risk_rating: 7, kyb_status: 'VERIFIED', kyb_next_review: null,
  rm_name: 'Layla Rahman', total_limit: '1000000.00', total_utilized: '950000.00', open_ews: 0,
}

function renderApp(routes: Record<string, () => Response>) {
  vi.stubGlobal('fetch', vi.fn(async (input: Request) => {
    const path = new URL(input.url).pathname
    const handler = routes[`${input.method} ${path}`]
    return handler ? handler() : json(404, { detail: 'not mocked' })
  }))
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}><App /></QueryClientProvider>)
}

afterEach(() => vi.unstubAllGlobals())

describe('App', () => {
  it('shows the sign-in form when signed out, and signs in', async () => {
    let signedIn = false
    renderApp({
      'GET /api/auth/me': () => (signedIn ? json(200, RM) : json(401, { detail: 'Not signed in' })),
      'GET /api/info': () => json(200, { environment: 'test', llm_provider: 'mock', dev_persona_switch: false, default_currency: 'BHD' }),
      'POST /api/auth/login': () => { signedIn = true; return json(200, RM) },
      'GET /api/accounts': () => json(200, [ACCOUNT]),
    })
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText('Password'), 'demo1234')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByText('Good day, Layla')).toBeInTheDocument()
    expect(screen.getByText('AI: mock mode')).toBeInTheDocument()
    // Compliance-only navigation is hidden for an RM.
    expect(screen.queryByRole('link', { name: /audit trail/i })).not.toBeInTheDocument()
  })

  it('shows a wrong-password message', async () => {
    renderApp({
      'GET /api/auth/me': () => json(401, { detail: 'Not signed in' }),
      'GET /api/info': () => json(200, { environment: 'test', llm_provider: 'mock', dev_persona_switch: false, default_currency: 'BHD' }),
      'POST /api/auth/login': () => json(401, { detail: 'Wrong email or password' }),
    })
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText('Password'), 'nope')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Wrong email or password')
  })
})
