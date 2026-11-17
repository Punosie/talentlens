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

  test('settings: model picker recommends the most accurate model that works here', async ({ page }) => {
    // a 2 GB laptop graphics card (GeForce MX250): accuracy first, so the 3B is recommended even
    // though part of it runs on the processor
    let current = 'qwen2.5:3b-instruct'
    await page.route('**/api/settings', async (route) => {
      if (route.request().method() !== 'GET') return route.continue()
      const res = await route.fetch()
      const body = await res.json()
      const models = [
        { id: 'qwen3.5:4b-q4_K_M', label: 'Qwen 3.5 4B (thinking)', hint: 'Careful.', size_gb: 3.3, think: true, recommended: false, fits: false },
        { id: 'qwen2.5:3b-instruct', label: 'Qwen 2.5 3B', hint: 'Quick and small.', size_gb: 1.9, think: null, recommended: true, fits: false },
        { id: 'qwen2.5:1.5b-instruct', label: 'Qwen 2.5 1.5B (low memory)', hint: 'Fastest.', size_gb: 1, think: null, recommended: false, fits: true },
      ]
      body.ai = {
        ...body.ai,
        enabled: true,
        locked: false,
        model: current,
        models,
        installed: models.map((m) => m.id),
        recommended_model: 'qwen2.5:3b-instruct',
        hardware: { gpu: 'NVIDIA GeForce MX250', vram_gb: 2, ram_gb: 15.8, budget_gb: 2 },
      }
      await route.fulfill({ response: res, json: body })
    })
    await page.goto('/settings')
    const select = page.getByTestId('ai-model-select')
    await expect(select.locator('option', { hasText: 'Qwen 2.5 3B' })).toHaveText(/recommended for this computer.*slower here/)
    await expect(select.locator('option', { hasText: '1.5B' })).not.toHaveText(/recommended/)
    const fit = page.getByTestId('ai-model-fit')
    await expect(fit).toContainText("your graphics card's 2 GB")
    await expect(fit).toContainText('still the most accurate choice')

    // a model that is both too big and not the pick points to the recommended one
    current = 'qwen3.5:4b-q4_K_M'
    await page.reload()
    await expect(fit).toContainText('Qwen 2.5 3B is the most accurate choice that works well on this computer')
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
