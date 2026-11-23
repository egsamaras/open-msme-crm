import { expect, test } from '@playwright/test'
import { approvalCard, goTo, signIn, viewAs } from './helpers'

test('draft a credit memo, then a credit officer edits and submits it', async ({ page }) => {
  await signIn(page, 'rm@demo.local')
  await goTo(page, 'Pipeline')
  await page.getByText('Gulf Spice', { exact: true }).click()
  const drawer = page.getByRole('dialog', { name: 'Gulf Spice' })
  await expect(drawer).toContainText('StageUnderwriting')

  await drawer.getByRole('button', { name: 'Draft credit memo' }).click()
  await expect(drawer).toContainText('Sent for four-eyes review.')
  await page.keyboard.press('Escape')

  await viewAs(page, 'credit')
  await goTo(page, 'Approvals')
  const memo = approvalCard(page, 'Submit a credit memo', 'Gulf Spice')
  // Ratios are computed by the system and shown locked beside the editable prose.
  await expect(memo).toContainText('Calculated by the system, not the model')
  await expect(memo.getByRole('row', { name: /DSCR with the new facility/ })).toContainText('×')
  const recommendation = memo.getByLabel('Preliminary risk grade and recommendation')
  await recommendation.fill('Recommend approval subject to a minimum DSCR covenant of 1.25x and quarterly accounts.')
  await memo.getByRole('button', { name: 'Approve with my edits' }).click()
  await expect(memo).toHaveCount(0)

  // The deal moved to Approval with the memo and its credit officer.
  await goTo(page, 'Pipeline')
  await page.getByText('Gulf Spice', { exact: true }).click()
  await expect(drawer).toContainText('StageApproval')
  await expect(drawer).toContainText('Approved for submission by Omar Faris')
  await drawer.getByText('Preliminary risk grade and recommendation').click()
  await expect(drawer).toContainText('minimum DSCR covenant of 1.25x')
})
