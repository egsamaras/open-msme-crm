import { useState, type FormEvent } from 'react'
import { useAppInfo, useLogin } from '@/auth'

const DEMO_ACCOUNTS = [
  ['rm@demo.local', 'Relationship manager'],
  ['rm2@demo.local', 'Relationship manager (other accounts)'],
  ['credit@demo.local', 'Credit officer'],
  ['compliance@demo.local', 'Compliance officer'],
] as const

export function LoginPage() {
  const info = useAppInfo()
  const login = useLogin()
  const [email, setEmail] = useState('rm@demo.local')
  const [password, setPassword] = useState('')

  function submit(e: FormEvent) {
    e.preventDefault()
    login.mutate({ email, password })
  }

  return (
    <div className="grid min-h-svh place-items-center bg-brand-900 px-4">
      <div className="w-full max-w-sm rounded-2xl bg-white p-8 shadow-xl">
        <h1 className="text-xl font-semibold">Open MSME CRM</h1>
        <p className="mt-1 text-sm text-slate-500">Sign in to your portfolio.</p>

        <form onSubmit={submit} className="mt-6 space-y-4">
          <div>
            <label htmlFor="email" className="text-sm font-medium">
              Email
            </label>
            <input
              id="email"
              type="text"
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              required
            />
          </div>
          <div>
            <label htmlFor="password" className="text-sm font-medium">
              Password
            </label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              required
            />
          </div>
          {login.isError && (
            <p role="alert" className="text-sm text-rose-700">
              {login.error.message}
            </p>
          )}
          <button
            type="submit"
            disabled={login.isPending}
            className="w-full rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60"
          >
            {login.isPending ? 'Signing in…' : 'Sign in'}
          </button>
        </form>

        {info.data?.environment === 'development' && (
          <div className="mt-6 rounded-lg bg-slate-50 p-3 text-xs text-slate-600">
            <p className="font-medium">Demo accounts (password from SEED_PASSWORD, default demo1234)</p>
            <ul className="mt-1 space-y-0.5">
              {DEMO_ACCOUNTS.map(([e, label]) => (
                <li key={e}>
                  <button type="button" className="underline" onClick={() => setEmail(e)}>
                    {e}
                  </button>{' '}
                  — {label}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  )
}
