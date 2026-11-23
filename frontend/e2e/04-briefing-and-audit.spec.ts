import { expect, test } from '@playwright/test'
import { goTo, openAccount, signIn, viewAs } from './helpers'

test('prepare a meeting briefing, then verify the audit chain', async ({ page }) => {
  await signIn(page, 'rm@demo.local')
  await openAccount(page, 'Dunes Freight')
  await page.getByRole('button', { name: 'Prepare briefing' }).click()
  const panel = page.getByRole('dialog', { name: 'Meeting briefing' })
  await expect(panel.getByRole('heading', { name: 'Talking points' })).toBeVisible()
  await expect(panel.getByRole('heading', { name: 'Product ideas' })).toBeVisible()
  await expect(panel).toContainText('FX line')

  await panel.getByRole('button', { name: 'Inspect what the agent did' }).click()
  const inspect = page.getByRole('dialog', { name: 'Agent run' })
  await expect(inspect).toContainText('compute_health_metrics')
  await expect(inspect).toContainText('Records the model used')

  await page.keyboard.press('Escape')
  await page.keyboard.press('Escape')
  await viewAs(page, 'compliance')
  await goTo(page, 'Audit trail')
  await expect(page.getByRole('status').filter({ hasText: 'Hash chain' })).toContainText('Hash chain intact')
  await expect(page.getByRole('cell', { name: 'approval.resolved' }).first()).toBeVisible()
})
