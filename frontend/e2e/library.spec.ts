import { expect, test } from '@playwright/test'
import { openSearch, rowNamed, waitIdle } from './helpers'

test.describe('search resumes', () => {
  test.beforeEach(async ({ page, request }) => {
    await waitIdle(request)
    await openSearch(page)
  })

  test('lists every resume, with the library status in the header', async ({ page }) => {
    await expect(page.getByTestId('result-count')).toHaveText(/\d+ resumes/)
    await expect(rowNamed(page, 'Alice Example')).toBeVisible()
    await expect(rowNamed(page, 'Bob Sample')).toBeVisible()
    await expect(rowNamed(page, 'Carol Placeholder')).toBeVisible()
    await expect(page.getByTestId('index-status-line')).toContainText('resumes')
  })

  test('free-text search ranks and highlights matches; "/" focuses search', async ({ page }) => {
    await page.locator('h1').click()
    await page.keyboard.press('/')
    await expect(page.getByTestId('search-input')).toBeFocused()
    await page.keyboard.type('airflow spark')
    await expect(page.getByTestId('result-row').first()).toContainText('Alice Example')
    await expect(page.getByTestId('result-row').first().locator('mark').first()).toBeVisible()
    await expect(page).toHaveURL(/q=airflow/)
  })

  test('example searches fill the box', async ({ page }) => {
    await page.getByRole('button', { name: 'Python developer' }).click()
    await expect(page.getByTestId('search-input')).toHaveValue('Python developer')
  })

  test('skill filter with match all / any, and active filter chips', async ({ page }) => {
    const picker = page.getByTestId('filter-skills')
    await picker.getByRole('button', { name: 'Choose Skills' }).click()
    await page.getByLabel('Filter Skills').fill('Python')
    await page.getByRole('option', { name: /^Python/ }).click()
    await page.getByLabel('Filter Skills').fill('SAP Retail')
    await page.getByRole('option', { name: /SAP Retail/ }).click()
    await page.keyboard.press('Escape')

    await expect(page.getByText('Nothing matches')).toBeVisible() // nobody has both
    await page.getByRole('button', { name: 'Match any' }).click()
    await expect(rowNamed(page, 'Bob Sample')).toBeVisible()
    await expect(rowNamed(page, 'Alice Example')).toBeVisible()
    await expect(rowNamed(page, 'Bob Sample').locator('span.bg-mark', { hasText: 'SAP Retail' })).toBeVisible()

    const chips = page.getByTestId('active-filters')
    await expect(chips).toContainText('Python')
    await chips.getByRole('button', { name: 'Remove Python' }).click()
    await expect(chips).not.toContainText('Python')
    await page.getByTestId('clear-filters').click()
    await expect(page.getByTestId('active-filters')).toHaveCount(0)
  })

  test('years presets and manual range', async ({ page }) => {
    await page.getByRole('button', { name: /^10–15 yrs/ }).click()
    await expect(rowNamed(page, 'Bob Sample')).toBeVisible()
    await expect(rowNamed(page, 'Alice Example')).toHaveCount(0)
    await expect(page.getByTestId('active-filters')).toContainText('10–15 yrs')

    await page.getByRole('button', { name: /^10–15 yrs/ }).click() // toggle off
    await page.getByTestId('filter-years-min').fill('6')
    await page.getByTestId('filter-years-max').fill('8')
    await expect(rowNamed(page, 'Alice Example')).toBeVisible()
    await expect(page.getByTestId('result-row')).toHaveCount(1)
  })

  test('fast successive filter edits are never lost (no stale state)', async ({ page }) => {
    // two clicks in the same JS task: React can't re-render in between
    await page.evaluate(() => {
      const btn = [...document.querySelectorAll('button')].find((b) => b.textContent?.startsWith('10–15'))!
      btn.click()
      btn.click()
    })
    await expect(page.getByTestId('active-filters')).toHaveCount(0) // toggled on, then off
    await expect(page).not.toHaveURL(/ymin/)
    await page.evaluate(() => {
      const btn = [...document.querySelectorAll('button')].find((b) => b.textContent?.startsWith('3–6'))!
      btn.click()
    })
    await expect(page.getByTestId('active-filters')).toContainText('3–6 yrs')
  })

  test('location and industry filters', async ({ page }) => {
    await page.getByTestId('filter-location').getByRole('button', { name: 'Choose Location' }).click()
    await page.getByLabel('Filter Location').fill('Riyadh')
    await page.getByRole('option', { name: /Riyadh/ }).click()
    await page.keyboard.press('Escape')
    await expect(page.getByTestId('result-row')).toHaveCount(1)
    await expect(rowNamed(page, 'Carol Placeholder')).toBeVisible()

    await page.getByTestId('clear-filters').click()
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

  test('candidate profile: overview, resume preview, source; original file served', async ({ page }) => {
    await rowNamed(page, 'Alice Example').click()
    const drawer = page.getByTestId('cv-drawer')
    await expect(drawer.getByRole('heading', { name: 'Alice Example' })).toBeVisible()
    await expect(drawer).toContainText('alice@example.com')
    await expect(drawer).toContainText('Bengaluru')

    await drawer.getByRole('tab', { name: 'Resume' }).click()
    await expect(drawer.locator('iframe[title="Resume of Alice Example"]')).toBeVisible()
    await drawer.getByRole('tab', { name: 'File & source' }).click()
    await expect(drawer).toContainText('Alice_Example_Resume.pdf')
    await drawer.getByText('Show the text TalentLens read').click()
    await expect(drawer).toContainText('Airflow')

    const download = page.waitForEvent('download')
    await drawer.getByRole('button', { name: 'Download' }).click()
    expect((await download).suggestedFilename()).toBe('Alice_Example_Resume.pdf')

    // headless Chromium turns PDF popups into downloads, so capture the URL window.open gets
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
    expect(opened[0]).toMatch(/^\/api\/cvs\/\d+\/file$/)
    const inline = await page.request.get(opened[0]!)
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
