import { expect, test } from '@playwright/test'

/**
 * Optional smoke test against YOUR running TalentLens with the real local LLM (Ollama).
 * Skipped unless TL_REAL_URL is set, e.g.
 *   $env:TL_REAL_URL="http://127.0.0.1:8765"; npm run test:e2e:real
 * It only reads data and asks the LLM to parse a JD; nothing is written.
 */
const base = process.env.TL_REAL_URL

test.describe('real local AI smoke', () => {
  test.skip(!base, 'TL_REAL_URL not set')
  test.setTimeout(240_000)

  test('Ollama is reachable and parses a JD into requirements', async ({ request }) => {
    const health = await (await request.get(`${base}/api/health`)).json()
    expect(health.llm.available, health.llm.error ?? '').toBe(true)

    const res = await request.post(`${base}/api/jd/parse`, {
      multipart: {
        mode: 'ai',
        text:
          'Telecom CVM Manager in Dubai. 8+ years. Must have churn analytics, campaign management, ' +
          'customer segmentation and SQL. Nice to have: Python, Braze.',
      },
      timeout: 220_000,
    })
    const body = await res.json()
    expect(body.warning).toBeNull()
    expect(body.requirements.source).toBe('llm')
    expect(body.requirements.must_have_skills.length).toBeGreaterThan(1)
  })
})
