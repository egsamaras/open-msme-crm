import { useId } from 'react'
import type { User } from '@/api/client'
import { usePersonas, useSwitchPersona } from '@/auth'
import { ROLE_LABEL } from '@/lib/format'

/** Development only: become any seeded persona. The backend returns 404 outside development. */
export function PersonaSwitcher({ current }: { current: User }) {
  const id = useId()
  const personas = usePersonas(true)
  const switchPersona = useSwitchPersona()

  if (!personas.data) return null
  return (
    <div className="flex items-center gap-2 text-sm">
      <label htmlFor={id} className="text-xs text-slate-500">
        View as
      </label>
      <select
        id={id}
        value={current.id}
        disabled={switchPersona.isPending}
        onChange={(e) => switchPersona.mutate(e.target.value)}
        className="rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-sm"
      >
        {personas.data.map((p) => (
          <option key={p.id} value={p.id}>
            {ROLE_LABEL[p.role]} — {p.full_name}
          </option>
        ))}
      </select>
    </div>
  )
}
