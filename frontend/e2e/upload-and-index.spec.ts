import { expect, test } from '@playwright/test'
import crypto from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'
import { cvDir, openLibrary, rowNamed, sample, waitIdle } from './helpers'

const digestFolder = () =>
  Object.fromEntries(
    fs
      .readdirSync(cvDir())
      .sort()
      .map((f) => [f, crypto.createHash('sha256').update(fs.readFileSync(path.join(cvDir(), f))).digest('hex')]),
  )

test.describe.serial('adding resumes and re-indexing', () => {
  test('upload through the UI: new, duplicate and invalid files', async ({ page, request }) => {
    await waitIdle(request)
    const before = digestFolder()
    await page.goto('/upload')
    await page
      .getByTestId('file-input')
      .setInputFiles([sample('Dave_Fixture_Resume.pdf'), sample('alice-copy.pdf'), sample('not-really.pdf')])

    const results = page.getByTestId('upload-results')
    await expect(results.locator('[data-status="added"]')).toContainText('Dave_Fixture_Resume.pdf')
    await expect(results.locator('[data-status="duplicate"]')).toContainText('Already in the library')
    await expect(results.locator('[data-status="rejected"]')).toContainText('not a valid PDF')

    // existing files are byte-identical; exactly one new file was added
    const after = digestFolder()
    for (const [name, hash] of Object.entries(before)) expect(after[name]).toBe(hash)
    expect(Object.keys(after).filter((k) => !(k in before))).toEqual(['Dave_Fixture_Resume.pdf'])
  })

  test('the upload is indexed automatically and appears in the library', async ({ page, request }) => {
    await waitIdle(request)
    await openLibrary(page)
    await page.getByTestId('search-input').fill('terraform kubernetes')
    await expect(page.getByTestId('result-row').first()).toContainText('Dave Fixture')
  })

  test('a file dropped straight into the folder is picked up by the watcher', async ({ page, request }) => {
    fs.copyFileSync(sample('Erin_Dropin.pdf'), path.join(cvDir(), 'Erin_Dropin.pdf'))
    await expect
      .poll(async () => (await (await request.get('/api/search?q=Erin')).json()).total, { timeout: 30_000 })
      .toBeGreaterThan(0)
    await openLibrary(page)
    await expect(rowNamed(page, 'Erin Dropin')).toBeVisible()
  })

  test('refresh button re-scans and reports progress', async ({ page, request }) => {
    await waitIdle(request)
    await openLibrary(page)
    const before = (await (await request.get('/api/index/status')).json()).version
    await page.getByTestId('refresh-button').click()
    await expect
      .poll(async () => (await (await request.get('/api/index/status')).json()).version, { timeout: 15_000 })
      .toBeGreaterThan(before)
    await waitIdle(request)
    await expect(page.getByTestId('index-status-line')).toContainText(/5 resumes/)
  })

  test('full re-index from the menu keeps everything searchable', async ({ page, request }) => {
    await openLibrary(page)
    await page.getByRole('button', { name: 'More index actions' }).click()
    await page.getByRole('menuitem', { name: /Full re-index/ }).click()
    await expect(page.getByText('Full re-index started')).toBeVisible()
    await waitIdle(request)
    const r = await (await request.get('/api/cvs')).json()
    expect(r.total).toBe(5)
    expect(r.items.every((i: { status: string }) => i.status === 'indexed')).toBe(true)
  })
})
