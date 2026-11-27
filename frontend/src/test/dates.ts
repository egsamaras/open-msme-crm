/** Dates relative to today, and a timezone switch, for tests of how dates read on screen. */
import { expect, vi } from 'vitest'

function localDay(days: number): Date {
  const d = new Date()
  d.setDate(d.getDate() + days)
  return d
}

/** The local date `days` from today, as the API sends it (`YYYY-MM-DD`). */
export function inDays(days: number): string {
  const d = localDay(days)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

/** The same date as a person reads it ("26 Nov 2026"), worked out from the local calendar. */
export function shown(days: number): string {
  return new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }).format(localDay(days))
}

/**
 * Runs the rest of the test in `zone`; `vi.unstubAllEnvs()` switches back. Changing TZ at run time
 * works in vitest's forks pool (set in vite.config.ts), so fail loudly if it didn't take.
 */
export function inTimezone(zone: string): void {
  vi.stubEnv('TZ', zone)
  expect(Intl.DateTimeFormat().resolvedOptions().timeZone).toBe(zone)
}
