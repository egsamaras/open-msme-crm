import { expect, test } from '@playwright/test'
import { signIn } from './helpers'

test('unknown pages and records show a clear message, and a failed call can be retried', async ({ page }) => {
  await signIn(page, 'rm@demo.local')
  await page.goto('/no-such-page')
  await expect(page.getByRole('heading', { name: 'Not found' })).toBeVisible()

  await page.goto('/accounts/00000000-0000-0000-0000-000000000000')
  await expect(page.getByRole('alert')).toContainText('No such account')

  // Simulate the alerts API being down: the page shows the error, and recovers on retry.
  let down = true
  await page.route(/\/api\/ews\?/, async (route) => {
    if (down) await route.fulfill({ status: 503, contentType: 'application/json', body: '{"detail":"Service unavailable"}' })
    else await route.continue()
  })
  await page.goto('/risk')
  await expect(page.getByRole('alert')).toContainText('Service unavailable')
  down = false
  await page.getByRole('button', { name: 'Try again' }).click()
  await expect(page.getByRole('alert')).toHaveCount(0)
})
