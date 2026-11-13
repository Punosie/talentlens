// Records the TalentLens setup walkthrough (video + one screenshot per scene) with Playwright.
// Run through make_manual.py, which starts TalentLens (:8765) and the mock team server (:8790)
// with fictional data. Env: MANUAL_OUT, MANUAL_WORK, MANUAL_RESUMES, MANUAL_NEW_RESUME.
import { createRequire } from 'node:module'
import { mkdirSync, renameSync, readdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { SCENES, INSTALL_COMMANDS, JD_TEXT } from './scenes.mjs'

const here = path.dirname(fileURLToPath(import.meta.url))
const require = createRequire(path.join(here, '../../frontend/package.json'))
const { chromium } = require('playwright')

const OUT = process.env.MANUAL_OUT
const WORK = process.env.MANUAL_WORK
const SHOTS = path.join(OUT, 'img')
const APP = 'http://127.0.0.1:8765'
const TEAM = 'http://127.0.0.1:8790'
const INVITE = `${TEAM}/join/DemoInviteCode0123456789Ab`
const W = 1440, H = 900
mkdirSync(SHOTS, { recursive: true })
mkdirSync(WORK, { recursive: true })

const scene = Object.fromEntries(SCENES.map((s, i) => [s.id, { ...s, n: i + 1 }]))
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const readTime = (text) => Math.max(3800, text.split(/\s+/).length * 330) + 600

const browser = await chromium.launch()
const ctx = await browser.newContext({
  viewport: { width: W, height: H },
  deviceScaleFactor: 1,
  recordVideo: { dir: WORK, size: { width: W, height: H } },
  colorScheme: 'light',
})
const page = await ctx.newPage()
page.setDefaultTimeout(30_000)
const t0 = Date.now()

// Waiting on the AI or a sync is cut out of the video afterwards (make_manual.py), keeping a short
// moment at each end so viewers see that something is happening.
const cuts = []
async function waitCut(fn, keep = 1500) {
  const a = (Date.now() - t0) / 1000 + keep / 1000
  await fn()
  const b = (Date.now() - t0) / 1000 - 0.6
  if (b - a > 1) cuts.push([+a.toFixed(2), +b.toFixed(2)])
}

// ---------- overlay: caption bar, step chip and a visible mouse pointer ----------
let curPos = `translate(${W / 2}px,${H / 2}px)`
async function overlay() {
  await page.evaluate((curPos) => {
    if (document.getElementById('__man')) return
    const css = document.createElement('style')
    css.textContent = `
      #__man{position:fixed;left:50%;bottom:28px;transform:translateX(-50%);z-index:2147483646;max-width:1040px;
        width:calc(100% - 160px);display:flex;gap:14px;align-items:flex-start;padding:16px 22px;border-radius:14px;
        background:rgba(17,17,17,.9);color:#fff;font:500 21px/1.45 "Segoe UI Variable Text","Segoe UI",system-ui,sans-serif;
        box-shadow:0 12px 40px rgba(0,0,0,.25);transition:opacity .35s ease, transform .35s ease;pointer-events:none}
      #__man.hide{opacity:0;transform:translateX(-50%) translateY(10px)}
      #__man b{flex:none;font:600 13px/1 "Segoe UI",system-ui,sans-serif;letter-spacing:.04em;text-transform:uppercase;
        background:#fff;color:#111;border-radius:999px;padding:7px 10px;margin-top:3px}
      #__cur{position:fixed;left:0;top:0;width:22px;height:22px;z-index:2147483647;pointer-events:none;
        transition:transform .7s cubic-bezier(.4,0,.2,1)}
      #__cur.click::after{content:"";position:absolute;left:-14px;top:-14px;width:28px;height:28px;border-radius:50%;
        border:3px solid rgba(37,99,235,.7);animation:__p .5s ease-out}
      @keyframes __p{from{transform:scale(.3);opacity:1}to{transform:scale(1.6);opacity:0}}`
    document.head.appendChild(css)
    const bar = document.createElement('div')
    bar.id = '__man'
    bar.className = 'hide'
    bar.innerHTML = '<b></b><span></span>'
    document.body.appendChild(bar)
    const cur = document.createElement('div')
    cur.id = '__cur'
    cur.innerHTML = '<svg width="22" height="22" viewBox="0 0 24 24"><path d="M4 2l15 11-6.5 1.2L16 21l-3 1.4-3.4-6.8L4 20z" fill="#111" stroke="#fff" stroke-width="1.5" stroke-linejoin="round"/></svg>'
    document.body.appendChild(cur)
    cur.style.transform = curPos
  }, curPos)
}

async function caption(s) {
  await overlay()
  await page.evaluate(({ n, total, text }) => {
    const bar = document.getElementById('__man')
    bar.querySelector('b').textContent = `Step ${n} of ${total}`
    bar.querySelector('span').textContent = text
    bar.classList.remove('hide')
  }, { n: s.n, total: SCENES.length, text: s.caption })
}

async function screenshot(id) {
  await page.evaluate(() => {
    for (const id of ['__man', '__cur']) { const e = document.getElementById(id); if (e) e.style.visibility = 'hidden' }
  }).catch(() => {})
  await page.screenshot({ path: path.join(SHOTS, `${id}.png`) })
  await page.evaluate(() => {
    for (const id of ['__man', '__cur']) { const e = document.getElementById(id); if (e) e.style.visibility = '' }
  }).catch(() => {})
}

async function moveTo(locator) {
  await locator.scrollIntoViewIfNeeded()
  const b = await locator.boundingBox()
  if (!b) return
  await overlay()
  const t = `translate(${Math.round(b.x + Math.min(b.width / 2, 60))}px,${Math.round(b.y + b.height / 2)}px)`
  curPos = t
  await page.evaluate((t) => { document.getElementById('__cur').style.transform = t }, t)
  await sleep(800)
}

async function click(locator) {
  await moveTo(locator)
  await page.evaluate(() => {
    const c = document.getElementById('__cur'); c.classList.remove('click'); void c.offsetWidth; c.classList.add('click')
  })
  await sleep(180)
  await locator.click()
}

async function type(locator, text, delay = 45) {
  await click(locator)
  await locator.pressSequentially(text, { delay })
}

// show a scene: caption, hold long enough to read, screenshot in the middle
async function show(id, { hold, before } = {}) {
  const s = scene[id]
  await caption(s)
  if (before) await before()
  await sleep(700)
  await screenshot(id)
  await sleep(hold ?? readTime(s.caption))
}

// ---------- full-screen cards for steps that happen outside the app ----------
const FONT = '"Segoe UI Variable Text","Segoe UI",system-ui,sans-serif'
const esc = (t) => t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
function cardHtml(s, inner) {
  return `<!doctype html><html><head><meta charset="utf-8"><style>
  *{box-sizing:border-box} body{margin:0;height:100vh;font-family:${FONT};color:#171717;
  background:radial-gradient(1200px 600px at 20% 0%,#eef2ff 0,transparent 60%),radial-gradient(900px 500px at 100% 100%,#f0fdf4 0,transparent 55%),#fafafa;
  display:flex;align-items:center;justify-content:center}
  .w{width:1040px;padding-bottom:110px;animation:in .6s cubic-bezier(.2,.8,.2,1)} @keyframes in{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:none}}
  .sec{font:600 14px/1 ${FONT};letter-spacing:.08em;text-transform:uppercase;color:#4f46e5}
  h1{font-size:52px;letter-spacing:-.03em;margin:14px 0 18px;line-height:1.1} p.l{font-size:23px;line-height:1.55;color:#525252;margin:0;max-width:880px}
  ol{margin:28px 0 0;padding:0;list-style:none;display:grid;gap:14px} li{display:flex;gap:16px;font-size:22px;line-height:1.45;align-items:flex-start}
  li span.n{flex:none;width:34px;height:34px;border-radius:50%;background:#171717;color:#fff;font-size:15px;font-weight:600;display:flex;align-items:center;justify-content:center;margin-top:1px}
  .logo{display:flex;align-items:center;gap:12px;font-weight:600;font-size:22px;margin-bottom:40px}
  .logo i{width:40px;height:40px;border-radius:11px;background:#171717;display:flex;align-items:center;justify-content:center}
  .term{margin-top:26px;border-radius:12px;overflow:hidden;box-shadow:0 24px 60px rgba(0,0,0,.18);background:#0c1021}
  .term .bar{height:38px;background:#1f2433;display:flex;align-items:center;gap:8px;padding:0 14px;color:#cbd5e1;font-size:14px}
  .term .bar i{width:12px;height:12px;border-radius:50%;background:#475569}
  .term pre{margin:0;padding:22px 24px;color:#e2e8f0;font:16px/1.75 "Cascadia Mono",Consolas,monospace;white-space:pre-wrap}
  .term pre .p{color:#7dd3fc} .term pre .c{color:#94a3b8}
  .chat{margin-top:30px;display:flex;gap:16px;align-items:flex-start}
  .av{flex:none;width:52px;height:52px;border-radius:50%;background:#c7d2fe;display:flex;align-items:center;justify-content:center;font-weight:700;color:#3730a3;font-size:20px}
  .bub{background:#fff;border:1px solid #e5e5e5;border-radius:4px 18px 18px 18px;padding:20px 24px;font-size:21px;line-height:1.5;box-shadow:0 8px 30px rgba(0,0,0,.06);max-width:820px}
  .bub a{color:#2563eb;text-decoration:underline;word-break:break-all}
  </style></head><body><div class="w"><div class="sec">${esc(s.section)}</div><h1>${esc(s.title)}</h1>${inner}</div></body></html>`
}
const steps = (s) => `<ol>${s.steps.map((t, i) => `<li><span class="n">${i + 1}</span><span>${esc(t)}</span></li>`).join('')}</ol>`

async function card(id, inner) {
  const s = scene[id]
  await page.setContent(cardHtml(s, inner ?? (s.steps ? steps(s) : `<p class="l">${esc(s.body)}</p>`)))
  await show(id, { hold: readTime(s.caption) + (s.steps ? s.steps.length * 900 : 0) })
}

// ================================ the walkthrough ================================
const welcome = scene.welcome
await page.setContent(cardHtml(welcome, `<p class="l">${esc(welcome.body)}</p>`).replace(
  '<div class="w">',
  `<div class="w"><div class="logo"><i><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg></i>TalentLens</div>`,
))
await show('welcome')
await card('need')
await card('powershell')

const term = INSTALL_COMMANDS.map((c, i) => `<span class="c"># ${i + 1}</span>\n<span class="p">PS&gt;</span> ${esc(c)}`).join('\n\n')
await card('commands', `<div class="term"><div class="bar"><i></i><i></i><i></i>&nbsp; Windows PowerShell</div><pre>${term}</pre></div>`
  + `<p class="l" style="margin-top:22px;font-size:19px">${esc(scene.commands.steps[2])}</p>`)
await card('setup-runs')

// ---- first start: onboarding
await page.goto(APP)
await page.getByTestId('folder-path').waitFor()
await caption(scene.onboarding)
await sleep(1200)
await page.getByTestId('folder-path').fill('')
await type(page.getByTestId('folder-path'), process.env.MANUAL_RESUMES, 25)
await sleep(600)
await screenshot('onboarding')
await sleep(2200)
await click(page.getByTestId('folder-save'))
await page.getByTestId('onboarding-next').waitFor()
await waitCut(() => page.getByText(/ready to search/).waitFor({ timeout: 90_000 }).catch(() => {}))
await sleep(1500)
await click(page.getByTestId('onboarding-next'))
await sleep(1200)
await click(page.getByTestId('onboarding-done'))
await sleep(800)
await show('home')

// ---- invite link
await card('invite', `<div class="chat"><div class="av">A</div><div class="bub"><b>Alex (Talent team)</b><br>
  Hi Jordan! Here is your invite to our TalentLens connections. Open TalentLens first, then click:<br>
  <a id="lnk" href="${INVITE}">${INVITE}</a></div></div>`)
await click(page.locator('#lnk'))
await page.waitForURL(/\/join\//)
await show('join', { hold: 2600 })
await click(page.locator('#connect'))
await page.waitForURL(/\/connect\?/)
await page.getByTestId('connect-confirm').waitFor()
await show('confirm', { hold: 2600 })
await click(page.getByTestId('connect-confirm-btn'))
await waitCut(() => page.getByTestId('connect-done').waitFor())
await sleep(2500)

// ---- sync status
await click(page.getByRole('link', { name: 'Settings' }))
const status = page.getByTestId('connections-status')
await status.waitFor()
await status.evaluate((e) => e.scrollIntoView({ block: 'center', behavior: 'smooth' }))
await sleep(900)
await waitCut(() => page.waitForFunction(() => /\b24 connections\b/.test(document.querySelector('[data-testid=connections-status]')?.textContent ?? ''), null, { timeout: 120_000 }).catch(() => {}))
await moveTo(status)
await show('synced')

// ---- search + profile
await click(page.getByRole('link', { name: 'Search resumes' }))
await type(page.getByTestId('search-input'), 'data engineer', 70)
await page.keyboard.press('Enter')
await page.getByTestId('result-row').first().waitFor()
await sleep(800)
await moveTo(page.getByTestId('result-row').first())
await show('search')
const linkedInRow = page.getByTestId('result-row').filter({ hasText: /via @/ }).first()
await click((await linkedInRow.count()) ? linkedInRow : page.getByTestId('result-row').first())
await sleep(900)
await show('profile')
await page.keyboard.press('Escape')
await sleep(600)

// ---- match to a job
await click(page.getByRole('link', { name: 'Match to a job' }))
await page.getByTestId('jd-text').waitFor()
await caption(scene['match-jd'])
await click(page.getByTestId('jd-text'))
await page.getByTestId('jd-text').fill(JD_TEXT)
await sleep(900)
await screenshot('match-jd')
await sleep(readTime(scene['match-jd'].caption) - 1500)
await click(page.getByTestId('jd-submit'))
await waitCut(async () => {
  await page.getByTestId('requirements').waitFor({ timeout: 180_000 })
  await page.getByTestId('ai-refining').waitFor({ state: 'detached', timeout: 120_000 }).catch(() => {})
}, 2500)
await sleep(600)
await show('match-req', { before: () => moveTo(page.getByTestId('show-candidates')) })
await click(page.getByTestId('show-candidates'))
await waitCut(() => page.getByTestId('shortlist-row').first().waitFor({ timeout: 180_000 }), 2500)
await sleep(1500)
await moveTo(page.getByTestId('shortlist-row').first())
await show('match-results')
await page.mouse.wheel(0, 500)
await sleep(1800)

// ---- add resumes
await click(page.getByRole('link', { name: 'Add resumes' }))
await page.getByTestId('dropzone').waitFor()
await caption(scene.add)
await moveTo(page.getByTestId('dropzone'))
await sleep(1000)
await page.getByTestId('file-input').setInputFiles(process.env.MANUAL_NEW_RESUME)
await waitCut(() => page.getByText(/Ready to search/).first().waitFor({ timeout: 60_000 }).catch(() => {}), 2000)
await sleep(2500)
await screenshot('add')
await sleep(readTime(scene.add.caption) - 2000)

await card('done')
await sleep(800)

// ---------- finish: save the video under a stable name ----------
await ctx.close()
await browser.close()
const webm = readdirSync(WORK).filter((f) => f.endsWith('.webm') && f !== 'walkthrough.webm')
renameSync(path.join(WORK, webm[0]), path.join(WORK, 'walkthrough.webm'))
writeFileSync(path.join(WORK, 'cuts.json'), JSON.stringify(cuts))
console.log('cuts', JSON.stringify(cuts))
console.log('recorded', path.join(WORK, 'walkthrough.webm'))
