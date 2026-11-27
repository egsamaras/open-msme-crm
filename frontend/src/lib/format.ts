/** Shared number formatting. Amounts arrive from the API as decimal strings. */

export function toNumber(value: string | number): number {
  return typeof value === 'number' ? value : Number(value)
}

export function formatMoney(value: string | number, currency: string, compact = false): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
    notation: compact ? 'compact' : 'standard',
    maximumFractionDigits: compact ? 1 : 0,
    minimumFractionDigits: 0,
  }).format(toNumber(value))
}

/** Ratio of two decimal strings as a percentage, or null when the base is zero. */
export function percentOf(part: string | number, whole: string | number): number | null {
  const w = toNumber(whole)
  return w === 0 ? null : (toNumber(part) / w) * 100
}

export function formatPct(value: number | null, digits = 0): string {
  return value === null ? '—' : `${value.toFixed(digits)}%`
}

/** A calendar date with no time of day (`YYYY-MM-DD`), as the API sends due and expiry dates. */
const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/

/**
 * A date-only value is shown as written, in every timezone. `new Date('2026-11-26')` is midnight
 * UTC, which local time west of UTC shows as the day before. A timestamp is shown in local time.
 */
function formatWith(iso: string, options: Intl.DateTimeFormatOptions): string {
  const zone = DATE_ONLY.test(iso) ? { timeZone: 'UTC' } : {}
  return new Intl.DateTimeFormat('en-GB', { ...options, ...zone }).format(new Date(iso))
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  return formatWith(iso, { day: 'numeric', month: 'short', year: 'numeric' })
}

/** Calendar days from today (local) to a date-only value; negative once it has passed. */
export function daysUntil(iso: string, today: Date = new Date()): number {
  const start = Date.UTC(today.getFullYear(), today.getMonth(), today.getDate())
  const [y, m, d] = iso.split('-').map(Number)
  return Math.round((Date.UTC(y!, m! - 1, d!) - start) / 86_400_000)
}

/**
 * A document's expiry in words, the same on the Accounts list and the account's Documents tab.
 * `days` comes from `daysUntil`.
 */
export function expiryLabel(days: number): string {
  if (days < 0) return 'Expired'
  if (days === 0) return 'Expires today'
  return `${days} ${days === 1 ? 'day' : 'days'} left`
}

export const ROLE_LABEL: Record<string, string> = {
  RM: 'Relationship manager',
  CREDIT_OFFICER: 'Credit officer',
  COMPLIANCE: 'Compliance officer',
  ADMIN: 'Admin',
}

export function titleCase(value: string): string {
  return value.toLowerCase().replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase())
}

export const PRODUCT_LABEL: Record<string, string> = {
  WORKING_CAPITAL: 'Working capital',
  TERM_LOAN: 'Term loan',
  TRADE_FINANCE_LC: 'Trade finance (LC)',
  LETTER_OF_GUARANTEE: 'Letter of guarantee',
  POS_MERCHANT: 'POS merchant',
  FX_LINE: 'FX line',
  CASH_MANAGEMENT: 'Cash management',
  MURABAHA: 'Murabaha',
  IJARA: 'Ijara',
}

export const STAGE_LABEL: Record<string, string> = {
  LEAD: 'Lead',
  QUALIFICATION: 'Qualification',
  DOC_COLLECTION: 'Documents',
  CREDIT_UNDERWRITING: 'Underwriting',
  APPROVAL: 'Approval',
  DISBURSED: 'Disbursed',
  LOST: 'Lost',
}

export const DOC_LABEL: Record<string, string> = {
  TRADE_LICENSE: 'Trade licence',
  CR_CERTIFICATE: 'CR certificate',
  FINANCIAL_STATEMENT: 'Financial statements',
  BANK_STATEMENT: 'Bank statements',
  TAX_RETURN: 'Tax return',
  UBO_DECLARATION: 'UBO declaration',
}

export function formatRatio(value: string | null | undefined, digits = 2): string {
  return value == null ? '—' : `${toNumber(value).toFixed(digits)}×`
}

export function formatMonth(iso: string): string {
  return formatWith(iso, { month: 'short', year: '2-digit' })
}

export function formatDayMonth(iso: string): string {
  return formatWith(iso, { day: 'numeric', month: 'short' })
}
