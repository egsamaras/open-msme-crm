import { expect, test } from '@playwright/test'
import { approvalCard, goTo, signIn, viewAs } from './helpers'

test('scan the portfolio, approve outreach and an escalation, resolve an alert', async ({ page }) => {
  await signIn(page, 'rm@demo.local')
  await goTo(page, 'Risk radar')
  await expect(page.getByText('No open alerts')).toBeVisible()

  // The scan: fixed rules, then one review per flagged company, each waiting for approval.
  await page.getByRole('button', { name: 'Run portfolio scan' }).click()
  await expect(page.getByText('4 alerts across the portfolio, 4 new.')).toBeVisible()
  const reviews = page.getByRole('listitem').filter({ hasText: 'Waiting for approval' })
  await expect(reviews).toHaveCount(4)

  // The alert table fills in, most severe first, with the values that fired.
  const rows = page.getByRole('row')
  await expect(rows.filter({ hasText: 'Dunes Freight' })).toContainText('Cash-flow drop')
  await expect(rows.filter({ hasText: 'Falcon Steel' })).toContainText('above 90% for 35 days')
  await expect(rows.nth(1)).toContainText('High')

  // RM edits and approves the simulated email to Falcon Steel.
  await page.getByRole('link', { name: 'Review the proposals' }).click()
  const email = approvalCard(page, 'Send an email (simulated)', 'Falcon Steel')
  await email.getByLabel('Subject').fill('Quick catch-up this week?')
  await email.getByRole('button', { name: 'Approve with my edits' }).click()
  await expect(email).toHaveCount(0)

  // The RM can't approve an escalation: four-eyes needs a credit officer.
  const escalation = approvalCard(page, 'Escalate an early-warning alert', 'Dunes Freight')
  await expect(escalation).toContainText('Needs a credit officer to review.')
  await expect(escalation.getByRole('button', { name: 'Approve' })).toHaveCount(0)

  await viewAs(page, 'credit')
  await escalation.getByRole('button', { name: 'Approve' }).click()
  await expect(escalation).toHaveCount(0)
  await page.getByRole('tab', { name: 'Decided' }).click()
  await expect(approvalCard(page, 'Escalate an early-warning alert', 'Dunes Freight')).toContainText('Approved by Omar Faris')
  await expect(approvalCard(page, 'Send an email (simulated)', 'Falcon Steel')).toContainText('Edited and approved by Layla Rahman')

  // Back on the radar: Dunes is under investigation; resolve Oasis with a note.
  await goTo(page, 'Risk radar')
  await expect(rows.filter({ hasText: 'Dunes Freight' })).toContainText('Investigating')
  const oasis = rows.filter({ hasText: 'Oasis Clinics' })
  await oasis.getByRole('button', { name: 'Resolve…' }).click()
  await oasis.getByLabel('How was it resolved?').fill('Cheques re-presented and cleared')
  await oasis.getByRole('button', { name: 'Resolve', exact: true }).click()
  await page.getByRole('tab', { name: 'Resolved' }).click()
  await expect(page.getByRole('row').filter({ hasText: 'Oasis Clinics' })).toContainText('Cheques re-presented and cleared')
})
