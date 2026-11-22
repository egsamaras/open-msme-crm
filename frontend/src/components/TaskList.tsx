import { Link } from 'react-router'
import { useSetTaskStatus, type Task } from '@/api/queries'
import { Badge, EmptyState } from '@/components/ui'
import { daysUntil, formatDate } from '@/lib/format'

export function TaskList({ tasks, showCompany = true }: { tasks: Task[]; showCompany?: boolean }) {
  const setStatus = useSetTaskStatus()
  if (tasks.length === 0) return <EmptyState title="No open tasks" />
  return (
    <ul className="divide-y divide-slate-100 text-sm">
      {tasks.map((t) => {
        const days = t.due_date ? daysUntil(t.due_date) : null
        const done = t.status === 'DONE'
        return (
          <li key={t.id} className="flex items-start gap-3 py-2">
            <input
              type="checkbox"
              checked={done}
              disabled={setStatus.isPending}
              onChange={() => setStatus.mutate({ id: t.id, status: done ? 'OPEN' : 'DONE' })}
              aria-label={`Mark "${t.title}" as ${done ? 'open' : 'done'}`}
              className="mt-0.5 size-4 accent-brand-600"
            />
            <div className="min-w-0 flex-1">
              <div className={done ? 'text-slate-400 line-through' : 'font-medium'}>{t.title}</div>
              <div className="text-xs text-slate-500">
                {showCompany && (
                  <>
                    <Link to={`/accounts/${t.company_id}`} className="hover:underline">{t.company_name}</Link>
                    {' · '}
                  </>
                )}
                Due {formatDate(t.due_date)}
                {t.source === 'AGENT' && ' · proposed by an agent'}
              </div>
            </div>
            {!done && days !== null && days < 0 && <Badge tone="bad">Overdue</Badge>}
            {!done && days !== null && days >= 0 && days <= 3 && <Badge tone="warn">Due soon</Badge>}
          </li>
        )
      })}
    </ul>
  )
}
