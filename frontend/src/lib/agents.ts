export const AGENT_LABEL: Record<string, string> = {
  demo_followup: 'Follow-up suggester (demo)',
  ews_scan: 'Portfolio scan',
  ews_review: 'Early-warning review',
  briefing: 'Pre-meeting briefing',
  kyb_intake: 'KYB document check',
  cam_draft: 'Credit memo drafter',
}

/** Roles that may start a portfolio scan (the server enforces this). */
export const SCAN_ROLES = new Set(['RM', 'CREDIT_OFFICER', 'ADMIN'])

export const RUN_TONE: Record<string, 'info' | 'warn' | 'good' | 'bad' | 'neutral'> = {
  RUNNING: 'info',
  AWAITING_APPROVAL: 'warn',
  COMPLETED: 'good',
  REJECTED: 'neutral',
  FAILED: 'bad',
}
