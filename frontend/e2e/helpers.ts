import { expect, type Page } from '@playwright/test'

export const PERSONA = {
  rm: 'Relationship manager — Layla Rahman',
  credit: 'Credit officer — Omar Faris',
  compliance: 'Compliance officer — Noura Saleh',
} as const

/** Sign in through the login form (synthetic seed users, development password). */
export async function signIn(page: Page, email = 'rm@demo.local') {
  await page.goto('/')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill('demo1234')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: /Good day/ })).toBeVisible()
}

/** Switch persona with the development "View as" menu. */
export async function viewAs(page: Page, persona: keyof typeof PERSONA) {
  const menu = page.getByLabel('View as')
  await menu.selectOption({ label: PERSONA[persona] })
  await expect(page.getByText(PERSONA[persona].split(' — ')[1]!, { exact: true }).first()).toBeVisible()
}

export async function openAccount(page: Page, name: string) {
  await goTo(page, 'Accounts')
  await page.getByRole('link', { name, exact: true }).first().click()
  await expect(page.getByRole('heading', { level: 1, name })).toBeVisible()
}

/** Follow a link in the main navigation (its name may carry a badge, e.g. "Approvals 2 waiting"). */
export async function goTo(page: Page, section: string) {
  await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: new RegExp(`^${section}`) }).click()
}

/** An approval card on the Approvals page, by action heading and account. */
export function approvalCard(page: Page, action: string, company: string) {
  return page.getByRole('article', { name: `${action}: ${company}` })
}
