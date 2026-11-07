import { expect, test } from '@playwright/test'
import { openLibrary, rowNamed, waitIdle } from './helpers'

test.describe('library: search and filters', () => {
  test.beforeEach(async ({ page, request }) => {
    await waitIdle(request)
    await openLibrary(page)
  })

  test('lists every indexed resume with status in the header', async ({ page }) => {
    await expect(page.getByTestId('result-count')).toHaveText(/\d+ resumes/)
    await expect(rowNamed(page, 'Alice Example')).toBeVisible()
    await expect(rowNamed(page, 'Bob Sample')).toBeVisible()
    await expect(rowNamed(page, 'Carol Placeholder')).toBeVisible()
    await expect(page.getByTestId('index-status-line')).toContainText('resumes')
  })

  test('free-text search ranks and highlights matches', async ({ page }) => {
    await page.getByTestId('search-input').fill('airflow spark')
    await expect(page.getByTestId('result-row').first()).toContainText('Alice Example')
    await expect(page.getByTestId('result-row').first().locator('mark').first()).toBeVisible()
    await expect(page).toHaveURL(/q=airflow/)
  })

  test('skill filter with match all / any', async ({ page }) => {
    const picker = page.getByTestId('filter-skills')
    await picker.getByRole('button', { name: 'Choose Skills' }).click()
    await page.getByLabel('Filter Skills').fill('Python')
    await page.getByRole('option', { name: /^Python/ }).click()
    await page.getByLabel('Filter Skills').fill('SAP Retail')
    await page.getByRole('option', { name: /SAP Retail/ }).click()
    await page.keyboard.press('Escape')

    // nobody has both
    await expect(page.getByText('Nothing matches')).toBeVisible()
    await page.getByRole('button', { name: 'Match any' }).click()
    await expect(rowNamed(page, 'Bob Sample')).toBeVisible()
    await expect(rowNamed(page, 'Alice Example')).toBeVisible()
    // matched skills get the highlighter
    await expect(rowNamed(page, 'Bob Sample').locator('span.bg-mark', { hasText: 'SAP Retail' })).toBeVisible()
  })

  test('years presets and manual range', async ({ page }) => {
    await page.getByRole('button', { name: /^10–15/ }).click()
    await expect(rowNamed(page, 'Bob Sample')).toBeVisible()
    await expect(rowNamed(page, 'Alice Example')).toHaveCount(0)

    await page.getByRole('button', { name: /^10–15/ }).click() // toggle off
    await page.getByTestId('filter-years-min').fill('6')
    await page.getByTestId('filter-years-max').fill('8')
    await expect(rowNamed(page, 'Alice Example')).toBeVisible()
    await expect(page.getByTestId('result-row')).toHaveCount(1)
  })

  test('location and industry filters, then clear', async ({ page }) => {
    await page.getByTestId('filter-location').getByRole('button', { name: 'Choose Location' }).click()
    await page.getByLabel('Filter Location').fill('Riyadh')
    await page.getByRole('option', { name: /Riyadh/ }).click()
    await page.keyboard.press('Escape')
    await expect(page.getByTestId('result-row')).toHaveCount(1)
    await expect(rowNamed(page, 'Carol Placeholder')).toBeVisible()

    await page.getByRole('button', { name: 'Clear filters' }).click()
    await page.getByTestId('filter-domain').getByRole('button', { name: 'Choose Industry' }).click()
    await page.getByLabel('Filter Industry').fill('Retail')
    await page.getByRole('option', { name: /^Retail/ }).click()
    await page.keyboard.press('Escape')
    await expect(rowNamed(page, 'Bob Sample')).toBeVisible()
  })

  test('sorting by experience', async ({ page }) => {
    await page.getByTestId('sort-select').selectOption('experience')
    await expect(page.getByTestId('result-row').first()).toContainText('Bob Sample')
  })

  test('CV drawer shows details and serves the original file', async ({ page }) => {
    await rowNamed(page, 'Alice Example').click()
    const drawer = page.getByTestId('cv-drawer')
    await expect(drawer.getByRole('heading', { name: 'Alice Example' })).toBeVisible()
    await expect(drawer).toContainText('alice@example.com')
    await expect(drawer).toContainText('Bengaluru')
    await drawer.getByRole('button', { name: 'Show extracted text' }).click()
    await expect(drawer).toContainText('Airflow')

    const download = page.waitForEvent('download')
    await drawer.getByRole('button', { name: 'Download' }).click()
    expect((await download).suggestedFilename()).toBe('Alice_Example_Resume.pdf')

    // Headless Chromium turns PDF popups into downloads, so capture the URL window.open gets
    await page.evaluate(() => {
      const w = window as unknown as { __opened: string[] }
      w.__opened = []
      window.open = ((u: string) => {
        w.__opened.push(u)
        return null
      }) as typeof window.open
    })
    await drawer.getByRole('button', { name: 'Open original' }).click()
    const opened = await page.evaluate(() => (window as unknown as { __opened: string[] }).__opened)
    expect(opened).toHaveLength(1)
    expect(opened[0]).toMatch(/^\/api\/cvs\/\d+\/file$/)
    const inline = await page.request.get(opened[0])
    expect(inline.headers()['content-type']).toBe('application/pdf')
    expect(inline.headers()['content-disposition']).toMatch(/^inline/)

    await page.keyboard.press('Escape')
    await expect(drawer).toBeHidden()
  })

  test('theme toggle switches to dark and back', async ({ page }) => {
    const html = page.locator('html')
    const before = await html.getAttribute('class')
    await page.getByRole('button', { name: /Switch to (dark|light) theme/ }).click()
    await expect(html).not.toHaveAttribute('class', before ?? '')
  })
})
