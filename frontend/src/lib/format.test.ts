import { afterEach, describe, expect, it, vi } from 'vitest'
import { inTimezone } from '@/test/dates'
import {
  daysUntil,
  expiryLabel,
  formatDate,
  formatDayMonth,
  formatMoney,
  formatMonth,
  formatPct,
  percentOf,
  titleCase,
} from './format'

afterEach(() => vi.unstubAllEnvs())

describe('format', () => {
  it('formats decimal strings in the client currency', () => {
    expect(formatMoney('125000.00', 'BHD').replace(/\s/g, ' ')).toBe('BHD 125,000')
    expect(formatMoney('2500000', 'SAR', true).replace(/\s/g, ' ')).toBe('SAR 2.5M')
  })

  it('returns null utilisation for a zero limit instead of dividing by zero', () => {
    expect(percentOf('10', '0')).toBeNull()
    expect(formatPct(null)).toBe('—')
    expect(formatPct(percentOf('93.5', '100'), 1)).toBe('93.5%')
  })

  it('counts calendar days to a date', () => {
    expect(daysUntil('2026-12-01', new Date(2026, 10, 22))).toBe(9)
  })

  it('puts a document expiry into words', () => {
    expect(expiryLabel(-1)).toBe('Expired')
    expect(expiryLabel(0)).toBe('Expires today')
    expect(expiryLabel(1)).toBe('1 day left')
    expect(expiryLabel(30)).toBe('30 days left')
  })

  it('shows a date as written west of UTC, and a timestamp in local time', () => {
    inTimezone('America/New_York')
    // Due and expiry dates have no time of day: the same date in every timezone.
    expect(formatDate('2026-11-26')).toBe('26 Nov 2026')
    expect(formatMonth('2026-11-01')).toBe('Nov 26')
    expect(formatDayMonth('2026-11-26')).toBe('26 Nov')
    // 02:00 UTC on 26 Nov is still the evening of 25 Nov in New York.
    expect(formatDate('2026-11-26T02:00:00Z')).toBe('25 Nov 2026')
    // Days count from the local date: at 23:30 on 26 Nov in New York (27 Nov in UTC),
    // 27 Nov is still a day away, so the words match the date shown.
    expect(daysUntil('2026-11-27', new Date(2026, 10, 26, 23, 30))).toBe(1)
  })

  it('title-cases enum values', () => {
    expect(titleCase('PENDING_RENEWAL')).toBe('Pending renewal')
  })
})
