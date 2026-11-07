import { expect, type APIRequestContext, type Page } from '@playwright/test'
import path from 'node:path'

export const root = () => process.env.TL_E2E_ROOT!
export const cvDir = () => path.join(root(), 'cvs', 'files')
export const sample = (name: string) => path.join(root(), 'samples', name)

/** Wait until the background index (and the mock AI stage) is idle. */
export async function waitIdle(request: APIRequestContext, base = '', timeout = 45_000) {
  await expect
    .poll(
      async () => {
        const s = await (await request.get(`${base}/api/index/status`)).json()
        return s.state
      },
      { timeout, intervals: [250, 500, 1000] },
    )
    .toMatch(/^(idle|no_folder)$/)
}

export async function openSearch(page: Page) {
  await page.goto('/search')
  await expect(page.getByTestId('result-row').first()).toBeVisible()
}

export const rowNamed = (page: Page, name: string) => page.getByTestId('result-row').filter({ hasText: name })

/** Open the library status popover in the header. */
export async function openStatus(page: Page) {
  await page.getByTestId('index-status').click()
}
