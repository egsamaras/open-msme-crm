import { expect, test, type Page } from '@playwright/test'
import { approvalCard, goTo, openAccount, signIn, viewAs } from './helpers'

// `npm run screenshots` rebuilds the README images in docs/screenshots from a fresh database.
test.use({ deviceScaleFactor: 2, viewport: { width: 1440, height: 900 } })

const shot = (page: Page, name: string) =>
  page.screenshot({ path: `../docs/screenshots/${name}.png`, animations: 'disabled', caret: 'hide' })

test('capture README screenshots', async ({ page }) => {
  test.setTimeout(180_000)
  await signIn(page, 'rm@demo.local')

  // Risk radar after a scan.
  await goTo(page, 'Risk radar')
  await page.getByRole('button', { name: 'Run portfolio scan' }).click()
  await expect(page.getByRole('listitem').filter({ hasText: 'Waiting for approval' })).toHaveCount(4)
  await page.reload()
  await expect(page.getByRole('row').filter({ hasText: 'Dunes Freight' })).toBeVisible()
  await page.getByRole('row').filter({ hasText: 'Dunes Freight' }).getByText("Agent's root-cause analysis").click()
  await page.getByRole('tab', { name: 'Open' }).scrollIntoViewIfNeeded()
  await shot(page, 'risk-radar')

  // Command centre with the new alerts and approvals.
  await goTo(page, 'Command centre')
  await expect(page.getByText(/proposals? needs? your approval/)).toBeVisible()
  await shot(page, 'command-centre')

  // Account 360 with the briefing co-pilot open.
  await openAccount(page, 'Dunes Freight')
  await page.getByRole('button', { name: 'Prepare briefing' }).click()
  const briefing = page.getByRole('dialog', { name: 'Meeting briefing' })
  await expect(briefing.getByRole('heading', { name: 'Product ideas' })).toBeVisible()
  await shot(page, 'briefing')
  await page.keyboard.press('Escape')

  // Credit memo: drafted by the RM, reviewed by a credit officer.
  await goTo(page, 'Pipeline')
  await page.getByText('Gulf Spice', { exact: true }).click()
  const drawer = page.getByRole('dialog', { name: 'Gulf Spice' })
  await drawer.getByRole('button', { name: 'Draft credit memo' }).click()
  await expect(drawer).toContainText('Sent for four-eyes review.')
  await page.keyboard.press('Escape')

  // KYB check on the seeded ownership mismatch.
  await openAccount(page, 'Gulf Spice')
  await page.getByRole('tab', { name: /Owners & documents/ }).click()
  await page.getByRole('button', { name: 'Run KYB check' }).click()
  await expect(page.getByText('KYB check waiting for compliance review')).toBeVisible()

  await viewAs(page, 'credit')
  await goTo(page, 'Approvals')
  const memo = approvalCard(page, 'Submit a credit memo', 'Gulf Spice')
  await memo.evaluate((el) => el.scrollIntoView({ block: 'start' }))
  await page.evaluate(() => window.scrollBy(0, -24))
  await shot(page, 'credit-memo-review')
  await page.evaluate(() => window.scrollTo(0, 0))

  const escalation = approvalCard(page, 'Escalate an early-warning alert', 'Dunes Freight')
  await escalation.getByRole('button', { name: 'Inspect what the agent did' }).click()
  await expect(page.getByRole('dialog', { name: 'Agent run' })).toContainText('Records the model used')
  await shot(page, 'inspection-drawer')
  await page.keyboard.press('Escape')

  await viewAs(page, 'compliance')
  await goTo(page, 'Approvals')
  await expect(approvalCard(page, 'Update a KYB record', 'Gulf Spice')).toBeVisible()
  await shot(page, 'kyb-review')

  await goTo(page, 'Audit trail')
  await expect(page.getByRole('status').filter({ hasText: 'Hash chain' })).toContainText('Hash chain intact')
  await shot(page, 'audit-trail')
})
