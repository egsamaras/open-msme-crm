import { Link, isRouteErrorResponse, useRouteError } from 'react-router'
import { Card, EmptyState, PageHeader } from '@/components/ui'

export function NotFoundPage() {
  return (
    <>
      <PageHeader title="Not found" />
      <Card>
        <EmptyState title="This page doesn't exist">
          <p>
            Check the address, or go back to the <Link to="/" className="text-brand-700 underline">command centre</Link>.
          </p>
        </EmptyState>
      </Card>
    </>
  )
}

/** Shown inside the layout when a page crashes or its code fails to load. */
export function RouteError() {
  const error = useRouteError()
  const detail = isRouteErrorResponse(error) ? `${error.status} ${error.statusText}` : error instanceof Error ? error.message : null
  return (
    <>
      <PageHeader title="Something went wrong" />
      <Card>
        <div role="alert" className="space-y-3 p-8 text-sm">
          <p>This page hit an unexpected error. Nothing was changed; reloading usually fixes it, for example after a new version was deployed.</p>
          {detail && <p className="font-mono text-xs text-slate-500">{detail}</p>}
          <button type="button" onClick={() => window.location.reload()} className="btn-secondary">
            Reload the page
          </button>
        </div>
      </Card>
    </>
  )
}
