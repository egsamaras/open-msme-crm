import { describe, expect, it } from 'vitest'
import { daysUntil, formatMoney, formatPct, percentOf, titleCase } from './format'

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

  it('title-cases enum values', () => {
    expect(titleCase('PENDING_RENEWAL')).toBe('Pending renewal')
  })
})
