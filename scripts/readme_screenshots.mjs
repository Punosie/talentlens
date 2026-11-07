// Capture README screenshots from a demo instance with FICTIONAL resumes only.
//   1) uv run python backend/tests/e2e_server.py --demo --root <tmp> --port 8797
//   2) node scripts/readme_screenshots.mjs http://127.0.0.1:8797
// (run step 2 from the frontend folder so @playwright/test resolves)
import { chromium } from '@playwright/test'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const base = process.argv[2] ?? 'http://127.0.0.1:8797'
const out = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', 'docs', 'images')
const jd = readFileSync(
  path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', 'backend', 'tests', 'demo_data.py'),
  'utf8',
).split('DEMO_JD = """')[1].split('"""')[0]

const browser = await chromium.launch()
async function session(theme, width = 1440, height = 900) {
  const ctx = await browser.newContext({ viewport: { width, height }, colorScheme: theme, deviceScaleFactor: 1 })
  const page = await ctx.newPage()
  return { ctx, page }
}
const shot = (page, name) => page.screenshot({ path: path.join(out, `${name}.png`) })

// Library + search + drawer (light)
{
  const { ctx, page } = await session('light')
  await page.goto(base + '/?sort=experience')
  await page.getByTestId('result-row').first().waitFor()
  await shot(page, 'library')
  await page.goto(base + '/?skill=Churn%20Analytics&mode=any&skill=Campaign%20Management')
  await page.getByTestId('result-row').first().waitFor()
  await page.getByTestId('search-input').fill('telecom retention')
  await page.waitForTimeout(1200)
  await shot(page, 'search-filters')
  await page.getByTestId('result-row').first().click()
  await page.getByTestId('cv-drawer').waitFor()
  await page.waitForTimeout(600)
  await shot(page, 'resume-drawer')
  await ctx.close()
}
// Shortlist (light + dark)
for (const theme of ['light', 'dark']) {
  const { ctx, page } = await session(theme)
  await page.goto(base + '/shortlist')
  await page.evaluate(() => sessionStorage.clear())
  await page.goto(base + '/shortlist')
  await page.getByTestId('jd-text').fill(jd.trim())
  if (theme === 'light') await shot(page, 'jd-input')
  await page.getByTestId('jd-submit').click()
  await page.getByTestId('shortlist-row').first().waitFor()
  await page.getByTestId('ai-refining').waitFor({ state: 'hidden' })
  // wait until re-ranking after the AI refinement has fully settled
  await page.getByTestId('shortlist-count').filter({ hasText: 'candidates ranked' }).waitFor()
  await page.waitForTimeout(1500)
  await shot(page, theme === 'light' ? 'shortlist' : 'shortlist-dark')
  await ctx.close()
}
// Upload
{
  const { ctx, page } = await session('light', 1280, 760)
  await page.goto(base + '/upload')
  await shot(page, 'upload')
  await ctx.close()
}
await browser.close()
console.log('screenshots written to', out)
