export type Briefing = {
  company_id: string
  metrics: {
    health: 'GOOD' | 'WATCH' | 'CONCERN'
    dscr_latest: string | null
    revenue_change_pct: string | null
    balance_change_two_months_pct: string | null
    product_candidates: { product: string; reason: string }[]
  }
  briefing: {
    headline: string
    talking_points: string[]
    gaps: string[]
    product_ideas: { product: string; pitch: string }[]
  }
}

export const HEALTH = {
  GOOD: { label: 'Healthy', tone: 'good' },
  WATCH: { label: 'Worth watching', tone: 'warn' },
  CONCERN: { label: 'Concern', tone: 'bad' },
} as const
