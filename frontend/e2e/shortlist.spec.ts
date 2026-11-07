import { expect, test, type Page } from '@playwright/test'
import fs from 'node:fs'
import { sample, waitIdle } from './helpers'

async function freshShortlistPage(page: Page) {
  await page.goto('/shortlist')
  await page.evaluate(() => sessionStorage.clear())
  await page.goto('/shortlist')
}

test.describe('shortlisting against a JD', () => {
  test.beforeEach(async ({ page, request }) => {
    await waitIdle(request)
    await freshShortlistPage(page)
  })

  test('pasted JD → requirements → ranked candidates with breakdown', async ({ page }) => {
    await page.getByTestId('jd-text').fill(fs.readFileSync(sample('jd.txt'), 'utf8'))
    await page.getByTestId('jd-submit').click()

    const reqs = page.getByTestId('requirements')
    await expect(reqs.getByTestId('req-must')).toContainText('Python')
    await expect(reqs.getByTestId('req-location')).toContainText('Bengaluru')

    const first = page.getByTestId('shortlist-row').first()
    await expect(first).toContainText('Alice Example')
    await expect(first.locator('span.bg-mark', { hasText: 'Python' })).toBeVisible()
    await expect(first.getByTestId('score')).toHaveText(/\d+/)
    await expect(page.getByTestId('shortlist-count')).toContainText('candidates ranked')
  })

  test('uploading a JD file works too', async ({ page }) => {
    await page.getByTestId('jd-file').setInputFiles(sample('jd.txt'))
    await expect(page.getByText('jd.txt')).toBeVisible()
    await page.getByTestId('jd-submit').click()
    await expect(page.getByTestId('shortlist-row').first()).toContainText('Alice Example')
  })

  test('editing requirements re-ranks; explanation; save; export; delete', async ({ page }) => {
    await page.getByTestId('jd-text').fill(fs.readFileSync(sample('jd.txt'), 'utf8'))
    await page.getByTestId('jd-submit').click()
    await expect(page.getByTestId('shortlist-row').first()).toContainText('Alice Example')
    await expect(page.getByTestId('ai-refining')).toBeHidden() // let the AI pass land first

    const removeAll = async (testId: string) => {
      const buttons = page.getByTestId(testId).getByRole('button', { name: /^Remove / })
      while ((await buttons.count()) > 0) await buttons.first().click()
    }

    // swap the whole profile to a telecom role
    await page.getByLabel('Role').fill('RAN Engineer')
    await removeAll('req-nice')
    await removeAll('req-domain')
    await page.getByLabel('Minimum years required').fill('')
    await page.getByLabel('Maximum years').fill('')
    await removeAll('req-must')
    const must = page.getByTestId('req-must')
    await must.getByRole('button', { name: 'Choose Must-have skills' }).click()
    await page.getByLabel('Filter Must-have skills').fill('Ericsson')
    await page.getByRole('option', { name: /Ericsson/ }).click()
    await page.keyboard.press('Escape')
    await removeAll('req-location')
    await page.getByTestId('rerank').click()
    await expect(page.getByTestId('shortlist-row').first()).toContainText('Carol Placeholder')

    // on-demand explanation (mock LLM in tests)
    await page.getByTestId('shortlist-row').first().getByRole('button', { name: /Why this score/ }).click()
    await expect(page.getByTestId('explanation').first()).toContainText('Mock explanation')

    // CSV export of the current ranking
    const dl = page.waitForEvent('download')
    await page.getByTestId('export-csv').click()
    expect((await dl).suggestedFilename()).toMatch(/\.csv$/)

    // save the top 2 → lands on the saved detail page
    await page.getByTestId('shortlist-row').nth(0).getByRole('checkbox').check()
    await page.getByTestId('shortlist-row').nth(1).getByRole('checkbox').check()
    await page.getByTestId('save-open').click()
    await page.getByTestId('save-name').fill('Telecom RAN – e2e')
    await page.getByTestId('save-confirm').click()
    await expect(page.getByTestId('saved-title')).toHaveText('Telecom RAN – e2e')
    await expect(page.getByText(/^2 candidates · saved/)).toBeVisible()
    await expect(page.getByRole('status').filter({ hasText: 'with 2 candidates' })).toBeVisible() // toast

    const savedCsv = page.waitForEvent('download')
    await page.getByRole('button', { name: 'Export CSV' }).click()
    expect((await savedCsv).suggestedFilename()).toMatch(/Telecom RAN.*\.csv$/)

    await page.getByTestId('delete').click()
    await page.getByTestId('delete-confirm').click()
    await expect(page).toHaveURL(/\/saved$/)
    await expect(page.getByTestId('saved-list')).not.toContainText('Telecom RAN – e2e')
  })

  test('empty JD is refused with a clear message', async ({ page }) => {
    await page.getByTestId('jd-submit').click()
    await expect(page.getByText('Paste the job description or choose a file first')).toBeVisible()
  })
})
