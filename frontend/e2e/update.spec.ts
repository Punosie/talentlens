import { expect, test } from '@playwright/test'

const current = { current: '0.2.0', checked_at: null, error: null, can_update: true, last_run: null }

test.describe('forced update', () => {
  test('no update: the app is usable', async ({ page }) => {
    await page.route('**/api/update', (r) =>
      r.fulfill({ json: { ...current, latest: '0.2.0', update_required: false } }),
    )
    await page.goto('/')
    await expect(page.getByRole('navigation', { name: 'Main' })).toBeVisible()
    await expect(page.getByTestId('update-gate')).toHaveCount(0)
  })

  test('a newer version blocks the app until "Update now" is clicked', async ({ page }) => {
    let started = false
    await page.route('**/api/update', (r) => {
      if (r.request().method() === 'POST') {
        started = true
        return r.fulfill({ json: { ...current, latest: '0.3.0', update_required: true, started: true } })
      }
      return r.fulfill({ json: { ...current, latest: '0.3.0', update_required: true } })
    })
    await page.goto('/')
    const gate = page.getByTestId('update-gate')
    await expect(gate).toBeVisible()
    await expect(gate).toContainText('0.3.0')
    await expect(gate).toContainText('you have 0.2.0')
    // it can't be dismissed: Escape does nothing and there is no close button
    await page.keyboard.press('Escape')
    await expect(gate).toBeVisible()

    await page.getByTestId('update-now').click()
    await expect(page.getByTestId('update-progress')).toBeVisible()
    expect(started).toBe(true)
  })

  test('a failed attempt is explained and can be retried', async ({ page }) => {
    await page.route('**/api/update', (r) =>
      r.fulfill({
        json: {
          ...current,
          latest: '0.3.0',
          update_required: true,
          last_run: { state: 'failed', message: 'npm ci failed (exit code 1)' },
        },
      }),
    )
    await page.goto('/')
    await expect(page.getByTestId('update-error')).toContainText('npm ci failed')
    await expect(page.getByTestId('update-now')).toBeVisible()
  })

  test('a copy not installed from GitHub gets instructions instead of a button', async ({ page }) => {
    await page.route('**/api/update', (r) =>
      r.fulfill({ json: { ...current, can_update: false, latest: '0.3.0', update_required: true } }),
    )
    await page.goto('/')
    await expect(page.getByTestId('update-manual')).toBeVisible()
    await expect(page.getByTestId('update-now')).toHaveCount(0)
  })
})
