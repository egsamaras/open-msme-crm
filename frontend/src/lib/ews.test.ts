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

  it('says when the document an alert cites is no longer in force, without its stale day count', () => {
    const alert = (document_type: string, in_force: unknown) =>
      describeSignal('DOC_EXPIRY', { document_type, expiry_date: '2026-12-15', days_left: 18, threshold_days: 30, in_force })
    expect(alert('TRADE_LICENSE', { document_id: 'renewal-id', expiry_date: '2027-07-04' })).toBe(
      'Trade licence of 15 Dec 2026 is no longer in force: the one in force runs to 4 Jul 2027',
    )
    expect(alert('CR_CERTIFICATE', { document_id: null, expiry_date: null })).toBe(
      'CR certificate of 15 Dec 2026 is no longer in force, and none is in force now',
    )
    // No mark: the alert keeps its day count.
    expect(alert('TRADE_LICENSE', null)).toBe('Trade licence expires 15 Dec 2026 (in 18 days)')
  })
})
