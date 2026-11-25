import { expect, test } from '@playwright/test'
import { goTo, signIn, viewAs } from './helpers'

test('"View as" changes which accounts are listed and reachable', async ({ page }) => {
  await signIn(page, 'rm@demo.local')
  await goTo(page, 'Accounts')
  const rows = page.locator('tbody').getByRole('row')
  await expect(rows).toHaveCount(8)
  await expect(rows.filter({ hasText: 'Falcon Steel' })).toBeVisible()
  await expect(page.getByRole('columnheader', { name: 'RM' })).toHaveCount(0)

  await viewAs(page, 'rm2')
  await expect(rows).toHaveCount(7)
  await expect(rows.filter({ hasText: 'Falcon Steel' })).toHaveCount(0)
  await expect(rows.filter({ hasText: 'Tide Print' })).toBeVisible()

  await viewAs(page, 'credit')
  await expect(rows).toHaveCount(15)
  await expect(page.getByRole('columnheader', { name: 'RM', exact: true })).toBeVisible()

  await viewAs(page, 'compliance')
  await expect(rows).toHaveCount(15)
  await expect(page.getByRole('columnheader', { name: 'Next expiry' })).toBeVisible()

  // Switching while on an account the new persona can't see closes it off too.
  await rows.filter({ hasText: 'Pearl Bay Foods' }).getByRole('link').click()
  await expect(page.getByRole('heading', { level: 1, name: 'Pearl Bay Foods' })).toBeVisible()
  await viewAs(page, 'rm2')
  await expect(page.getByRole('alert')).toContainText('No such account')
})
