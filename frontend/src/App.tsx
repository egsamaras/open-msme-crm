import { createBrowserRouter, RouterProvider } from 'react-router'
import { lazy, Suspense, useMemo, type ReactNode } from 'react'
import type { User } from '@/api/client'
import { useMe } from '@/auth'
import { Layout } from '@/components/Layout'
import { ErrorState, Loading } from '@/components/ui'
import { AccountsPage } from '@/pages/AccountsPage'
import { CommandCentrePage } from '@/pages/CommandCentrePage'
import { LoginPage } from '@/pages/LoginPage'
import { PlaceholderPage } from '@/pages/PlaceholderPage'

// Chart-heavy pages load on demand to keep the first load small.
const AccountPage = lazy(() => import('@/pages/account/AccountPage').then((m) => ({ default: m.AccountPage })))
const PipelinePage = lazy(() => import('@/pages/pipeline/PipelinePage').then((m) => ({ default: m.PipelinePage })))

function Lazy({ children }: { children: ReactNode }) {
  return <Suspense fallback={<Loading />}>{children}</Suspense>
}

function buildRouter(user: User) {
  return createBrowserRouter([
    {
      element: <Layout user={user} />,
      children: [
        { index: true, element: <CommandCentrePage user={user} /> },
        { path: 'accounts', element: <AccountsPage /> },
        { path: 'accounts/:id', element: <Lazy><AccountPage /></Lazy> },
        { path: 'deals', element: <Lazy><PipelinePage /></Lazy> },
        {
          path: 'risk',
          element: (
            <PlaceholderPage title="Risk radar" phase={4}>
              Early-warning alerts ranked by severity, with the exact metric values that fired each one.
            </PlaceholderPage>
          ),
        },
        {
          path: 'approvals',
          element: (
            <PlaceholderPage title="Approvals" phase={3}>
              Every action an agent proposes waits here for a person to edit, approve or reject it.
            </PlaceholderPage>
          ),
        },
        {
          path: 'audit',
          element: (
            <PlaceholderPage title="Audit trail" phase={3}>
              The append-only, hash-chained log of every decision and agent step.
            </PlaceholderPage>
          ),
        },
        { path: '*', element: <PlaceholderPage title="Not found" phase={0}>This page doesn't exist.</PlaceholderPage> },
      ],
    },
  ])
}

function SignedIn({ user }: { user: User }) {
  // Rebuild routes when the persona changes, so role-specific pages update.
  const router = useMemo(() => buildRouter(user), [user])
  return <RouterProvider router={router} />
}

export default function App() {
  const me = useMe()
  if (me.isPending) return <Loading label="Starting…" />
  if (me.isError) return <ErrorState error={me.error} onRetry={() => void me.refetch()} />
  return me.data ? <SignedIn user={me.data} /> : <LoginPage />
}
