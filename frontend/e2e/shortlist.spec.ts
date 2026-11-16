import { expect, test, type Page } from '@playwright/test'
import fs from 'node:fs'
import { sample, waitIdle } from './helpers'

async function freshMatchPage(page: Page) {
  await page.goto('/match')
  await page.evaluate(() => sessionStorage.clear())
  await page.goto('/match')
}

test.describe('match to a job', () => {
  test.beforeEach(async ({ page, request }) => {
    await waitIdle(request)
    await freshMatchPage(page)
  })

  test('pasted JD → check requirements → ranked candidates with reasons', async ({ page }) => {
    await page.getByTestId('jd-text').fill(fs.readFileSync(sample('jd.txt'), 'utf8'))
    await page.getByTestId('jd-submit').click()

    const reqs = page.getByTestId('requirements')
    await expect(reqs.getByTestId('req-must')).toContainText('Python')
    await expect(reqs.getByTestId('req-location')).toContainText('Bengaluru')
    await expect(page.getByRole('listitem').filter({ hasText: 'Requirements' }).locator('[aria-current="step"]')).toBeVisible()

    await page.getByTestId('show-candidates').click()
    const first = page.getByTestId('shortlist-row').first()
    await expect(first).toContainText('Alice Example')
    await expect(first.locator('span.bg-mark', { hasText: 'Python' })).toBeVisible()
    await expect(first.getByTestId('match-label')).toHaveText(/(Excellent|Strong|Fair|Weak) match/)
    await expect(first.getByTestId('match-reason')).toContainText('must-have skill')
    await expect(page.getByTestId('shortlist-count')).toContainText('candidates ranked')

    // "New job" asks before throwing results away
    await page.getByTestId('new-jd').click()
    await page.getByRole('button', { name: 'Cancel' }).click()
    await expect(page.getByTestId('shortlist-row').first()).toBeVisible()

    await first.getByRole('button', { name: 'Score details' }).click()
    await expect(first).toContainText('Must-have skills')
  })

  test('filter the ranked results by a typed location, then clear', async ({ page }) => {
    await page.getByTestId('jd-text').fill(fs.readFileSync(sample('jd.txt'), 'utf8'))
    await page.getByTestId('jd-submit').click()
    await page.getByTestId('show-candidates').click()
    await expect(page.getByTestId('shortlist-row').first()).toContainText('Alice Example')
    const all = await page.getByTestId('shortlist-row').count()
    expect(all).toBeGreaterThan(1)

    const filters = page.getByTestId('result-filters')
    await filters.getByTestId('result-location').getByRole('button', { name: 'Choose Location' }).click()
    await page.getByLabel('Filter Location').fill('Riyadh, Saudi')
    await page.getByRole('button', { name: 'Add “Riyadh, Saudi”' }).click()
    await page.keyboard.press('Escape')
    await expect(page.getByTestId('shortlist-row')).toHaveCount(1)
    await expect(page.getByTestId('shortlist-row').first()).toContainText('Carol Placeholder')

    await page.getByTestId('clear-result-filters').click()
    await expect(page.getByTestId('shortlist-row')).toHaveCount(all)
  })

  test('uploading a JD file works too', async ({ page }) => {
    await page.getByTestId('jd-file').setInputFiles(sample('jd.txt'))
    await expect(page.getByText('jd.txt')).toBeVisible()
    await page.getByTestId('jd-submit').click()
    await page.getByTestId('show-candidates').click()
    await expect(page.getByTestId('shortlist-row').first()).toContainText('Alice Example')
  })

  test('edit requirements, explanation, bulk select, save, rename, export, delete', async ({ page }) => {
    await page.getByTestId('jd-text').fill(fs.readFileSync(sample('jd.txt'), 'utf8'))
    await page.getByTestId('jd-submit').click()
    await expect(page.getByTestId('ai-refining')).toBeHidden() // let smart reading land first

    const removeAll = async (testId: string) => {
      const buttons = page.getByTestId(testId).getByRole('button', { name: /^Remove / })
      while ((await buttons.count()) > 0) await buttons.first().click()
    }
    // turn it into a telecom role
    await page.getByLabel('Role').fill('RAN Engineer')
    await removeAll('req-nice')
    await removeAll('req-domain')
    await page.getByLabel('Minimum years required').fill('')
    await page.getByLabel('Maximum years').fill('')
    await removeAll('req-must')
    await page.getByTestId('req-must').getByRole('button', { name: 'Choose Must-have skills' }).click()
    await page.getByLabel('Filter Must-have skills').fill('Ericsson')
    await page.getByRole('option', { name: /Ericsson/ }).click()
    await page.keyboard.press('Escape')
    await removeAll('req-location')
    await page.getByTestId('show-candidates').click()
    await expect(page.getByTestId('shortlist-row').first()).toContainText('Carol Placeholder')

    // streamed explanation (mock AI in tests)
    await page.getByTestId('shortlist-row').first().getByRole('button', { name: /Why this score/ }).click()
    await expect(page.getByTestId('explanation').first()).toContainText('Mock explanation')

    // back to step 2 and forward again keeps the edits
    await page.getByTestId('edit-requirements').click()
    await expect(page.getByLabel('Role')).toHaveValue('RAN Engineer')
    await page.getByTestId('show-candidates').click()

    // export the current ranking
    const dl = page.waitForEvent('download')
    await page.getByTestId('export-csv').click()
    expect((await dl).suggestedFilename()).toMatch(/\.csv$/)

    // select two → bulk bar → save
    await page.getByTestId('shortlist-row').nth(0).getByRole('checkbox').check()
    await page.getByTestId('shortlist-row').nth(1).getByRole('checkbox').check()
    await expect(page.getByTestId('bulk-bar')).toContainText('2 selected')
    await page.getByTestId('bulk-bar').getByRole('button', { name: 'Save list' }).click()
    await page.getByTestId('save-name').fill('Telecom RAN – e2e')
    await page.getByTestId('save-confirm').click()
    await expect(page.getByTestId('saved-title')).toHaveText('Telecom RAN – e2e')
    await expect(page.getByText(/^2 candidates · saved/)).toBeVisible()

    await page.getByTestId('rename').click()
    await page.getByRole('dialog', { name: 'Rename list' }).getByRole('textbox').fill('RAN shortlist')
    await page.getByTestId('rename-confirm').click()
    await expect(page.getByTestId('saved-title')).toHaveText('RAN shortlist')

    const savedCsv = page.waitForEvent('download')
    await page.getByRole('button', { name: 'Export CSV' }).click()
    expect((await savedCsv).suggestedFilename()).toMatch(/RAN shortlist.*\.csv$/)

    await page.getByTestId('delete').click()
    await page.getByTestId('confirm').click()
    await expect(page).toHaveURL(/\/saved$/)
    await expect(page.getByTestId('saved-list')).not.toContainText('RAN shortlist')
  })

  test('empty JD is refused with a clear message', async ({ page }) => {
    await page.getByTestId('jd-submit').click()
    await expect(page.getByText('Paste the job description or choose a file first')).toBeVisible()
  })

  test('old /shortlist address redirects to Match', async ({ page }) => {
    await page.goto('/shortlist')
    await expect(page).toHaveURL(/\/match$/)
  })
})
