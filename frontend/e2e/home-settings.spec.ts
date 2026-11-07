import { expect, test } from '@playwright/test'
import { waitIdle } from './helpers'

test.describe('home, settings and help', () => {
  test.beforeEach(async ({ request }) => waitIdle(request))

  test('home shows actions, recent resumes and library stats', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(/Good (morning|afternoon|evening)/)
    await expect(page.getByTestId('home-match')).toBeVisible()
    await expect(page.getByText('Recently added')).toBeVisible()
    await expect(page.getByText('Most common skills')).toBeVisible()

    await page.getByTestId('home-search-input').fill('airflow')
    await page.keyboard.press('Enter')
    await expect(page).toHaveURL(/\/search\?q=airflow/)
    await expect(page.getByTestId('result-row').first()).toContainText('Alice Example')
  })

  test('home action cards navigate', async ({ page }) => {
    await page.goto('/')
    await page.getByTestId('home-add').click()
    await expect(page.getByRole('heading', { name: 'Add resumes' })).toBeVisible()
  })

  test('settings: folder set by configuration is shown read-only; theme choice', async ({ page }) => {
    await page.goto('/settings')
    await expect(page.getByTestId('current-folder')).toContainText('files')
    await expect(page.getByText('Set in the configuration file (.env)').first()).toBeVisible()
    await expect(page.getByTestId('change-folder')).toHaveCount(0)

    await page.getByRole('radio', { name: 'Dark' }).click()
    await expect(page.locator('html')).toHaveClass(/dark/)
    await page.getByRole('radio', { name: 'Light' }).click()
    await expect(page.locator('html')).not.toHaveClass(/dark/)
  })

  test('help answers and the welcome guide can be reopened', async ({ page }) => {
    await page.goto('/help')
    await page.getByText('Is my data uploaded anywhere?').click()
    await expect(page.getByText('runs entirely on this computer').first()).toBeVisible()
    await page.getByRole('button', { name: 'Show the welcome guide' }).click()
    await expect(page.getByRole('dialog', { name: 'Welcome to TalentLens' })).toBeVisible()
  })

  test('status popover explains smart reading in plain words', async ({ page }) => {
    await page.goto('/')
    await page.getByTestId('index-status').click()
    await expect(page.getByText('Smart reading', { exact: true })).toBeVisible()
    await expect(page.getByText('nothing leaves this computer')).toBeVisible()
  })
})
