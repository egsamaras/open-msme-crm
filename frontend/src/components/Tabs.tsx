import { useId, type KeyboardEvent } from 'react'
import { cn } from '@/lib/cn'

export type TabDef<K extends string> = { key: K; label: string; count?: number }

/** Accessible tab list (arrow keys move between tabs). Panels use `tabPanelProps`. */
export function Tabs<K extends string>({
  tabs,
  active,
  onChange,
  label,
}: {
  tabs: TabDef<K>[]
  active: K
  onChange: (key: K) => void
  label: string
}) {
  const base = useId()
  function onKey(e: KeyboardEvent, index: number) {
    const step = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0
    if (!step) return
    e.preventDefault()
    const next = tabs[(index + step + tabs.length) % tabs.length]!
    onChange(next.key)
    document.getElementById(`${base}-${next.key}`)?.focus()
  }
  return (
    <div role="tablist" aria-label={label} className="flex gap-1 overflow-x-auto border-b border-slate-200">
      {tabs.map((t, i) => (
        <button
          key={t.key}
          id={`${base}-${t.key}`}
          type="button"
          role="tab"
          aria-selected={t.key === active}
          tabIndex={t.key === active ? 0 : -1}
          onClick={() => onChange(t.key)}
          onKeyDown={(e) => onKey(e, i)}
          className={cn(
            '-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm transition-colors',
            t.key === active
              ? 'border-brand-600 font-medium text-brand-700'
              : 'border-transparent text-slate-500 hover:text-slate-800',
          )}
        >
          {t.label}
          {t.count !== undefined && (
            <span className="ml-1.5 rounded-full bg-slate-100 px-1.5 text-xs text-slate-600">{t.count}</span>
          )}
        </button>
      ))}
    </div>
  )
}
