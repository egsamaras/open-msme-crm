import type { Signal } from '@/api/risk'
import { DOC_LABEL, PRODUCT_LABEL, dayCount, formatDate, formatMoney } from '@/lib/format'

export const TRIGGER_LABEL: Record<string, string> = {
  CASHFLOW_DROP: 'Cash-flow drop',
  UTILIZATION_SPIKE: 'Utilisation spike',
  BOUNCED_CHEQUES: 'Bounced cheques',
  DOC_EXPIRY: 'Document expiring',
  COVENANT_BREACH: 'Covenant breach',
}

export const SEVERITY_TONE = { CRITICAL: 'bad', HIGH: 'bad', MEDIUM: 'warn', LOW: 'neutral' } as const

type Metrics = Record<string, unknown>
const s = (m: Metrics, k: string) => String(m[k] ?? '')

/** Days to an expiry in words, as `expiryLabel` counts them: "in 1 day", "today", "3 days ago". */
function expiryWhen(days: number): string {
  if (days < 0) return `${dayCount(-days)} ago`
  if (days === 0) return 'today'
  return `in ${dayCount(days)}`
}

/** The exact values that fired a signal, in words. */
export function describeSignal(trigger: Signal['trigger'], m: Metrics): string {
  switch (trigger) {
    case 'CASHFLOW_DROP': {
      const cur = s(m, 'currency')
      return `Average balance ${formatMoney(s(m, 'from_balance'), cur, true)} → ${formatMoney(s(m, 'to_balance'), cur, true)} (${s(m, 'change_pct')}%) from ${formatDate(s(m, 'from_period'))} to ${formatDate(s(m, 'to_period'))}; rule fires below ${s(m, 'threshold_pct')}%`
    }
    case 'UTILIZATION_SPIKE':
      return `${PRODUCT_LABEL[s(m, 'facility_product')] ?? s(m, 'facility_product')} above ${s(m, 'threshold_pct')}% for ${s(m, 'days_above')} days (latest ${s(m, 'latest_utilization_pct')}%); rule needs ${s(m, 'threshold_days')}+ days`
    case 'BOUNCED_CHEQUES':
      return `${s(m, 'count')} bounced cheque(s) in the month to ${formatDate(s(m, 'period'))}`
    case 'DOC_EXPIRY': {
      const doc = DOC_LABEL[s(m, 'document_type')] ?? s(m, 'document_type')
      const expiry = formatDate(s(m, 'expiry_date'))
      // The scan marks an alert whose document is no longer in force; its day count is then stale.
      const inForce = m.in_force
      if (typeof inForce === 'object' && inForce !== null) {
        const current = s(inForce as Metrics, 'expiry_date')
        return current
          ? `${doc} of ${expiry} is no longer in force: the one in force runs to ${formatDate(current)}`
          : `${doc} of ${expiry} is no longer in force, and none is in force now`
      }
      const days = Number(m.days_left)
      return `${doc} ${days < 0 ? 'expired' : 'expires'} ${expiry} (${expiryWhen(days)})`
    }
    case 'COVENANT_BREACH':
      return `${s(m, 'metric')} ${s(m, 'actual')} vs covenant ${s(m, 'operator')} ${s(m, 'threshold')} on ${PRODUCT_LABEL[s(m, 'facility_product')] ?? s(m, 'facility_product')}`
    default:
      return JSON.stringify(m)
  }
}
