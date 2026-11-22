import { Card, EmptyState, PageHeader } from '@/components/ui'

export function PlaceholderPage({ title, phase, children }: { title: string; phase: number; children: string }) {
  return (
    <>
      <PageHeader title={title} />
      <Card>
        <EmptyState title={`Coming in Phase ${phase}`}>
          <p className="max-w-md">{children}</p>
        </EmptyState>
      </Card>
    </>
  )
}
