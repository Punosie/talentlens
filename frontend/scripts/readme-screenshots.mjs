// Capture README screenshots from a demo instance with FICTIONAL resumes only.
//   1) uv run python backend/tests/e2e_server.py --demo --root <tmp> --port 8797
//   2) cd frontend && npm run screenshots -- http://127.0.0.1:8797
import { chromium } from '@playwright/test'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const base = process.argv[2] ?? 'http://127.0.0.1:8797'
const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..')
const out = path.join(repo, 'docs', 'images')
const jd = readFileSync(path.join(repo, 'backend', 'tests', 'demo_data.py'), 'utf8').split('DEMO_JD = """')[1].split('"""')[0]

const browser = await chromium.launch()
const shot = (page, name) => page.screenshot({ path: path.join(out, `${name}.png`) })

async function session(theme, width = 1440, height = 900) {
  const ctx = await browser.newContext({ viewport: { width, height }, colorScheme: theme })
  return { ctx, page: await ctx.newPage() }
}

// Home, search, profile
{
  const { ctx, page } = await session('light')
  await page.goto(base + '/')
  await page.getByText('Recently added').waitFor()
  await page.waitForTimeout(800)
  await shot(page, 'home')
  await page.goto(base + '/search?skill=Churn%20Analytics&skill=Campaign%20Management&mode=any')
  await page.getByTestId('result-row').first().waitFor()
  await page.waitForTimeout(600)
  await shot(page, 'search-filters')
  await page.getByTestId('result-row').first().click()
  await page.getByTestId('cv-drawer').waitFor()
  await page.waitForTimeout(600)
  await shot(page, 'resume-drawer')
  await ctx.close()
}

// Match wizard (light) and results (dark)
for (const theme of ['light', 'dark']) {
  const { ctx, page } = await session(theme)
  await page.goto(base + '/match')
  await page.evaluate(() => sessionStorage.clear())
  await page.goto(base + '/match')
  await page.getByTestId('jd-text').fill(jd.trim())
  if (theme === 'light') await shot(page, 'jd-input')
  await page.getByTestId('jd-submit').click()
  await page.getByTestId('requirements').waitFor()
  await page.getByTestId('ai-refining').waitFor({ state: 'hidden' }).catch(() => {})
  await page.waitForTimeout(4600) // let the toast fade
  if (theme === 'light') await shot(page, 'match-requirements')
  await page.getByTestId('show-candidates').click()
  await page.getByTestId('shortlist-count').filter({ hasText: 'fine-tuned' }).waitFor({ timeout: 60000 })
  if (theme === 'light') await page.getByTestId('shortlist-row').first().getByRole('button', { name: 'Score details' }).click()
  await page.waitForTimeout(800)
  await shot(page, theme === 'light' ? 'shortlist' : 'shortlist-dark')
  await ctx.close()
}

// Add resumes, settings, phone view
{
  const { ctx, page } = await session('light', 1280, 820)
  await page.goto(base + '/add')
  await page.waitForTimeout(500)
  await shot(page, 'upload')
  await page.goto(base + '/settings')
  await page.waitForTimeout(600)
  await shot(page, 'settings')
  await ctx.close()
}
{
  const { ctx, page } = await session('light', 390, 844)
  await page.goto(base + '/')
  await page.getByText('Recently added').waitFor()
  await page.waitForTimeout(600)
  await shot(page, 'phone-home')
  await ctx.close()
}
await browser.close()
console.log('screenshots written to', out)
