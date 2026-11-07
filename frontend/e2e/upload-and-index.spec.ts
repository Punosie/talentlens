import { expect, test } from '@playwright/test'
import crypto from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'
import { cvDir, openSearch, openStatus, rowNamed, sample, waitIdle } from './helpers'

const digestFolder = () =>
  Object.fromEntries(
    fs
      .readdirSync(cvDir(), { recursive: true, withFileTypes: true })
      .filter((d) => d.isFile())
      .map((d) => path.join(d.parentPath ?? (d as unknown as { path: string }).path, d.name))
      .sort()
      .map((f) => [path.relative(cvDir(), f), crypto.createHash('sha256').update(fs.readFileSync(f)).digest('hex')]),
  )

test.describe.serial('adding resumes and keeping the library up to date', () => {
  test('choose files: new, duplicate and invalid files in the upload panel', async ({ page, request }) => {
    await waitIdle(request)
    const before = digestFolder()
    await page.goto('/add')
    await page.getByTestId('file-input').setInputFiles([sample('Dave_Fixture_Resume.pdf'), sample('alice-copy.pdf'), sample('not-really.pdf')])

    const tray = page.getByTestId('upload-tray')
    await expect(tray).toBeVisible()
    const rows = page.getByTestId('upload-results')
    await expect(rows.locator('[data-status="ready"]')).toContainText('Dave_Fixture_Resume.pdf')
    await expect(rows.locator('[data-status="duplicate"]')).toContainText('Already in your library')
    await expect(rows.locator('[data-status="rejected"]')).toContainText('not a valid PDF')
    await expect(page.getByTestId('upload-tray-title')).toContainText('1 added · 1 already in library · 1 need attention')

    const after = digestFolder()
    for (const [name, hash] of Object.entries(before)) expect(after[name]).toBe(hash)
    expect(Object.keys(after).filter((k) => !(k in before))).toEqual(['Dave_Fixture_Resume.pdf'])
  })

  test('uploaded resumes are searchable straight away', async ({ page, request }) => {
    await waitIdle(request)
    await openSearch(page)
    await page.getByTestId('search-input').fill('terraform kubernetes')
    await expect(page.getByTestId('result-row').first()).toContainText('Dave Fixture')
  })

  test('choose a whole folder (subfolders included, non-resumes skipped)', async ({ page, request }) => {
    await page.goto('/add')
    await page.getByTestId('folder-input').setInputFiles(sample('batch-folder'))
    const rows = page.getByTestId('upload-results')
    await expect(rows.locator('[data-status="ready"]', { hasText: 'Fiona_Folder.pdf' })).toBeVisible()
    await expect(rows.locator('[data-status="ready"]', { hasText: 'George_Folder.docx' })).toBeVisible()
    await expect(rows).not.toContainText('notes.txt')
    await waitIdle(request)
    expect((await (await request.get('/api/search?q=George')).json()).total).toBe(1)
  })

  test('upload a ZIP of resumes', async ({ page, request }) => {
    await page.goto('/add')
    await page.getByTestId('zip-input').setInputFiles(sample('resumes.zip'))
    const rows = page.getByTestId('upload-results')
    await expect(rows.locator('[data-status="ready"]', { hasText: 'Hana_Zipped.pdf' })).toBeVisible()
    await expect(rows.locator('[data-status="ready"]', { hasText: 'Ivan_Zipped.pdf' })).toBeVisible()
    await expect(rows.locator('[data-status="skipped"]', { hasText: 'readme.txt' })).toBeVisible()
    await waitIdle(request)
    expect((await (await request.get('/api/search?q=Figma')).json()).items[0].name).toBe('Hana Zipped')
  })

  test('a file dropped straight into the folder is picked up automatically', async ({ page, request }) => {
    fs.copyFileSync(sample('Erin_Dropin.pdf'), path.join(cvDir(), 'Erin_Dropin.pdf'))
    await expect
      .poll(async () => (await (await request.get('/api/search?q=Erin')).json()).total, { timeout: 30_000 })
      .toBeGreaterThan(0)
    await openSearch(page)
    await expect(rowNamed(page, 'Erin Dropin')).toBeVisible()
  })

  test('"Check folder for new resumes" re-scans', async ({ page, request }) => {
    await waitIdle(request)
    await openSearch(page)
    const before = (await (await request.get('/api/index/status')).json()).version
    await openStatus(page)
    await page.getByTestId('refresh-button').click()
    await expect
      .poll(async () => (await (await request.get('/api/index/status')).json()).version, { timeout: 15_000 })
      .toBeGreaterThan(before)
    await waitIdle(request)
    await page.keyboard.press('Escape')
    await expect(page.getByTestId('index-status-line')).toContainText(/9 resumes/)
  })

  test('rebuild library keeps everything searchable', async ({ page, request }) => {
    await openSearch(page)
    await openStatus(page)
    await page.getByTestId('rebuild-button').click()
    await expect(page.getByText('Rebuilding your library')).toBeVisible()
    await waitIdle(request)
    const r = await (await request.get('/api/cvs')).json()
    expect(r.total).toBe(9)
    expect(r.items.every((i: { status: string }) => i.status === 'indexed')).toBe(true)
  })
})
