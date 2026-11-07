import { expect, test } from '@playwright/test'
import fs from 'node:fs'
import { sample, waitIdle } from './helpers'

test.describe('backend API', () => {
  test.beforeEach(async ({ request }) => waitIdle(request))

  test('health reports the fixture folder and mock AI', async ({ request }) => {
    const h = await (await request.get('/api/health')).json()
    expect(h.status).toBe('ok')
    expect(h.cv_dir_exists).toBe(true)
    expect(h.llm.mode).toBe('mock')
  })

  test('facets and filtered search', async ({ request }) => {
    const f = await (await request.get('/api/facets')).json()
    expect(f.skills.map((s: { value: string }) => s.value)).toContain('Python')

    const r = await (
      await request.get('/api/search', { params: { q: 'airflow spark', years_min: 5 } })
    ).json()
    expect(r.items[0].name).toBe('Alice Example')

    const loc = await (await request.get('/api/search?location=Saudi%20Arabia')).json()
    expect(loc.items.map((i: { name: string }) => i.name)).toEqual(['Carol Placeholder'])
  })

  test('upload rejects duplicates and fake files without touching the folder', async ({ request }) => {
    const res = await request.post('/api/cvs', {
      multipart: {
        files: { name: 'alice-copy.pdf', mimeType: 'application/pdf', buffer: fs.readFileSync(sample('alice-copy.pdf')) },
      },
    })
    const body = await res.json()
    expect(body.results[0].status).toBe('duplicate')

    const fake = await request.post('/api/cvs', {
      multipart: {
        files: { name: 'not-really.pdf', mimeType: 'application/pdf', buffer: fs.readFileSync(sample('not-really.pdf')) },
      },
    })
    expect((await fake.json()).results[0].status).toBe('rejected')
  })

  test('JD parse + shortlist + CSV export', async ({ request }) => {
    const parsed = await (
      await request.post('/api/jd/parse', { multipart: { text: fs.readFileSync(sample('jd.txt'), 'utf8') } })
    ).json()
    expect(parsed.requirements.must_have_skills).toContain('Python')

    const sl = await (
      await request.post('/api/shortlist', { data: { requirements: parsed.requirements, jd_text: parsed.jd_text } })
    ).json()
    expect(sl.items[0].name).toBe('Alice Example')

    const csv = await request.post('/api/shortlist/export', {
      data: { name: 'api test', jd_text: parsed.jd_text, requirements: parsed.requirements, results: sl.items },
    })
    expect(csv.headers()['content-type']).toContain('text/csv')
    expect(await csv.text()).toContain('Alice Example')
  })

  test('unknown routes return 404 JSON for the API and the app shell otherwise', async ({ request }) => {
    expect((await request.get('/api/does-not-exist')).status()).toBe(404)
    const shell = await request.get('/some/deep/link')
    expect(shell.status()).toBe(200)
    expect(await shell.text()).toContain('<div id="root">')
  })
})
