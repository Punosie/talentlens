import { expect, test } from '@playwright/test'
import path from 'node:path'

// Runs against the second server, started with no resume folder chosen yet.
const base = () => process.env.TL_E2E_FIRST_RUN_URL!
const firstRunRoot = () => process.env.TL_E2E_FIRST_RUN_ROOT!

test.describe.serial('first run: choosing the resume folder', () => {
  test('welcome guide → bad path is explained → good folder is checked → library reads it', async ({ page }) => {
    await page.goto(`${base()}/`)
    const dialog = page.getByRole('dialog', { name: 'Welcome to TalentLens' })
    await expect(dialog).toBeVisible()
    await expect(dialog.getByText('only reads')).toBeVisible()

    // a path that doesn't exist: friendly message, button disabled
    await dialog.getByTestId('folder-path').fill(path.join(firstRunRoot(), 'nope'))
    await expect(dialog.getByTestId('folder-check')).toContainText("doesn't exist")
    await expect(dialog.getByTestId('folder-save')).toBeDisabled()

    // the real folder: live count
    await dialog.getByTestId('folder-path').fill(path.join(firstRunRoot(), 'choose-me'))
    await expect(dialog.getByTestId('folder-check')).toContainText('Found 1 resume')
    await dialog.getByTestId('folder-save').click()

    await expect(page.getByRole('dialog', { name: 'Reading your resumes' })).toBeVisible()
    await expect(page.getByText('Done: 1 resume ready to search.')).toBeVisible({ timeout: 30_000 })
    await page.getByTestId('onboarding-next').click()
    await expect(page.getByRole('dialog', { name: "You're all set" })).toBeVisible()
    await page.getByRole('button', { name: /Search resumes/ }).click()

    await expect(page).toHaveURL(/\/search$/)
    await expect(page.getByTestId('result-row').first()).toContainText('Julia Onboard')
  })

  test('the guide does not come back after finishing; folder can be switched in Settings', async ({ page }) => {
    await page.goto(`${base()}/settings`)
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await expect(page.getByTestId('current-folder')).toContainText('choose-me')

    await page.getByTestId('change-folder').click()
    await page.getByTestId('folder-path').fill(path.join(firstRunRoot(), 'cvs', 'files'))
    await expect(page.getByTestId('folder-check')).toContainText('Found 3 resumes')
    await page.getByTestId('folder-save').click()
    await expect(page.getByText('Folder changed')).toBeVisible()
    await expect(page.getByTestId('current-folder')).toContainText('files')

    await page.goto(`${base()}/search`)
    await expect(page.getByTestId('result-row').filter({ hasText: 'Alice Example' })).toBeVisible()
    await expect(page.getByTestId('result-row').filter({ hasText: 'Julia Onboard' })).toHaveCount(0)
  })
})
