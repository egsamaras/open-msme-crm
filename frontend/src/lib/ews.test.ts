import { describe, expect, it } from 'vitest'
import { describeSignal } from './ews'

describe('describeSignal', () => {
  it('puts a document expiry into words: one day, today, and after it has passed', () => {
    const expiry = (days_left: number, expiry_date: string) =>
      describeSignal('DOC_EXPIRY', { document_type: 'TRADE_LICENSE', expiry_date, days_left, threshold_days: 30 })
    expect(expiry(18, '2026-12-15')).toBe('Trade licence expires 15 Dec 2026 (in 18 days)')
    expect(expiry(1, '2026-11-28')).toBe('Trade licence expires 28 Nov 2026 (in 1 day)')
    expect(expiry(0, '2026-11-27')).toBe('Trade licence expires 27 Nov 2026 (today)')
    expect(expiry(-1, '2026-11-26')).toBe('Trade licence expired 26 Nov 2026 (1 day ago)')
    expect(expiry(-5, '2026-11-22')).toBe('Trade licence expired 22 Nov 2026 (5 days ago)')
  })
})
