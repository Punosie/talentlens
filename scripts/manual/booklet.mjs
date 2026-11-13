// Builds docs/manual/TalentLens-Setup-Guide.pdf from scenes.mjs and the screenshots record.mjs saved.
import { createRequire } from 'node:module'
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import os from 'node:os'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { SCENES, INSTALL_COMMANDS } from './scenes.mjs'

const here = path.dirname(fileURLToPath(import.meta.url))
const require = createRequire(path.join(here, '../../frontend/package.json'))
const { chromium } = require('playwright')

const OUT = process.env.MANUAL_OUT ?? path.join(here, '../../docs/manual')
const esc = (t) => t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
const img = (id) => {
  const f = path.join(OUT, 'img', `${id}.png`)
  return existsSync(f) ? `data:image/png;base64,${readFileSync(f).toString('base64')}` : null
}
// card scenes are plain text in the booklet; these get a picture
const PICTURED = new Set(['onboarding', 'home', 'invite', 'join', 'confirm', 'synced', 'search', 'profile', 'match-jd', 'match-req', 'match-results', 'add'])

const sections = []
for (const [i, s] of SCENES.entries()) {
  const last = sections.at(-1)
  if (!last || last.name !== s.section) sections.push({ name: s.section, scenes: [] })
  sections.at(-1).scenes.push({ ...s, n: i + 1 })
}

function sceneHtml(s) {
  const pic = PICTURED.has(s.id) && img(s.id)
  const list = s.steps ? `<ol>${s.steps.map((t) => `<li>${esc(t)}</li>`).join('')}</ol>` : ''
  const body = s.body ? `<p>${esc(s.body)}</p>` : ''
  const cmds = s.id === 'commands'
    ? `<div class="cmds">${INSTALL_COMMANDS.map((c, i) => `<div><span>${i + 1}</span><code>${esc(c)}</code></div>`).join('')}</div>`
    : ''
  return `<article class="${pic ? 'pic' : ''}"><div class="num">Step ${s.n}</div><h3>${esc(s.title)}</h3>${body}${cmds}${list}
    ${pic ? `<figure><img src="${pic}"></figure>` : ''}</article>`
}

const cover = img('match-results') ?? img('home')
const html = `<!doctype html><html><head><meta charset="utf-8"><style>
@page{size:A4;margin:16mm 16mm 18mm}
*{box-sizing:border-box} body{margin:0;font:10.5pt/1.55 "Segoe UI",system-ui,sans-serif;color:#1c1c1c}
.cover{height:257mm;display:flex;flex-direction:column;justify-content:center;page-break-after:always}
.cover .k{font-size:10pt;font-weight:600;letter-spacing:.12em;text-transform:uppercase;color:#4f46e5}
.cover h1{font-size:38pt;line-height:1.05;letter-spacing:-.02em;margin:6mm 0 4mm} .cover p{font-size:13pt;color:#555;max-width:150mm;margin:0}
.cover img{margin-top:12mm;width:100%;border-radius:3mm;border:1px solid #e5e5e5;box-shadow:0 6mm 14mm rgba(0,0,0,.12)}
.cover .meta{margin-top:8mm;font-size:9pt;color:#777}
.toc{page-break-after:always} .toc h2{font-size:20pt;margin:0 0 8mm}
.toc ol{padding:0;list-style:none;margin:0} .toc li{display:flex;justify-content:space-between;border-bottom:1px solid #eee;padding:3mm 0;font-size:12pt}
.toc li span{color:#777}
.box{border:1px solid #e5e5e5;border-radius:3mm;padding:5mm 6mm;background:#fafafa;margin-top:10mm}
.box h3{margin:0 0 2mm;font-size:11.5pt}
section{margin-top:4mm} section h2{break-after:avoid;font-size:20pt;letter-spacing:-.01em;margin:0 0 6mm;padding-bottom:3mm;border-bottom:2px solid #171717}
article{break-inside:avoid;margin:0 0 7mm} .num{font-size:8.5pt;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:#4f46e5}
article h3{font-size:14pt;margin:1mm 0 2mm} article p{margin:0 0 2mm}
article ol{margin:2mm 0 0;padding-left:6mm} article li{margin:1mm 0}
figure{margin:4mm 0 0;text-align:center} figure img{width:122mm;border:1px solid #ddd;border-radius:2mm;box-shadow:0 2mm 6mm rgba(0,0,0,.08)}
.cmds{margin:3mm 0;border-radius:2mm;background:#0c1021;padding:4mm 5mm} .cmds div{display:flex;gap:3mm;margin:1.5mm 0}
.cmds span{color:#7dd3fc;font:700 9pt Consolas,monospace;flex:none;width:4mm} .cmds code{color:#e2e8f0;font:9pt/1.5 Consolas,monospace;word-break:break-all}
</style></head><body>
<div class="cover"><div class="k">Setup guide</div><h1>TalentLens</h1>
<p>Install TalentLens, connect to your team with an invite link, and find the right people for a job. No technical knowledge needed.</p>
${cover ? `<img src="${cover}">` : ''}<div class="meta">All people and companies shown in this guide are fictional.</div></div>
<div class="toc"><h2>Contents</h2><ol>${sections.map((s) => `<li>${esc(s.name)}<span>Steps ${s.scenes[0].n}–${s.scenes.at(-1).n}</span></li>`).join('')}</ol>
<div class="box"><h3>Prefer to watch?</h3>The same walkthrough is available as a short video: <b>docs/manual/TalentLens-Setup-Video.mp4</b> in the TalentLens repository.</div>
<div class="box"><h3>Your privacy</h3>TalentLens and its AI run on your own computer. Your resume files are only read, never changed or uploaded. Team connections arrive through your personal invite, which your team can remove at any time.</div></div>
${sections.map((s) => `<section><h2>${esc(s.name)}</h2>${s.scenes.map(sceneHtml).join('')}</section>`).join('')}
</body></html>`

const tmp = path.join(os.tmpdir(), 'talentlens-booklet.html')
writeFileSync(tmp, html)
const browser = await chromium.launch()
const page = await browser.newPage()
await page.goto(pathToFileURL(tmp).href)
await page.pdf({
  path: path.join(OUT, 'TalentLens-Setup-Guide.pdf'),
  format: 'A4',
  printBackground: true,
  displayHeaderFooter: true,
  headerTemplate: '<div></div>',
  footerTemplate: '<div style="width:100%;font:8px Segoe UI,sans-serif;color:#999;padding:0 16mm;display:flex;justify-content:space-between"><span>TalentLens setup guide</span><span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>',
  margin: { top: '16mm', bottom: '18mm', left: '16mm', right: '16mm' },
})
await browser.close()
