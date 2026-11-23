export const AGENT_LABEL: Record<string, string> = { demo_followup: 'Follow-up suggester (demo)' }

export const RUN_TONE: Record<string, 'info' | 'warn' | 'good' | 'bad' | 'neutral'> = {
  RUNNING: 'info',
  AWAITING_APPROVAL: 'warn',
  COMPLETED: 'good',
  REJECTED: 'neutral',
  FAILED: 'bad',
}
