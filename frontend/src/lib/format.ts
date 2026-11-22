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

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
    .format(new Date(iso))
}

export function daysUntil(iso: string, today: Date = new Date()): number {
  const start = Date.UTC(today.getFullYear(), today.getMonth(), today.getDate())
  const [y, m, d] = iso.split('-').map(Number)
  return Math.round((Date.UTC(y!, m! - 1, d!) - start) / 86_400_000)
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
  return new Intl.DateTimeFormat('en-GB', { month: 'short', year: '2-digit' }).format(new Date(iso))
}

export function formatDayMonth(iso: string): string {
  return new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short' }).format(new Date(iso))
}
