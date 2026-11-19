// 화면 점검: 주요 페이지를 휴대폰·태블릿·PC 크기로 열어 오류를 찾고 캡처를 남겨요.
//   node tools/smoke.js [주소=http://127.0.0.1:8099] [캡처폴더=임시폴더]
// 실패가 하나라도 있으면 종료 코드 1.
const { chromium } = require('playwright');
const fs = require('fs'), os = require('os'), path = require('path');
const B = (process.argv[2] || 'http://127.0.0.1:8099').replace(/\/$/, '');
const OUT = process.argv[3] || fs.mkdtempSync(path.join(os.tmpdir(), 'teemofarm-shots-'));
fs.mkdirSync(OUT, { recursive: true });

const SIZES = {
  phone: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true },
  tablet: { viewport: { width: 820, height: 1180 }, hasTouch: true },
  pc: { viewport: { width: 1440, height: 1000 } },
};
// [주소, 꼭 있어야 하는 요소들]
const PAGES = [
  ['/lck', ['.brand', '.top_tab']],
  ['/lck/roster', ['.brand', '.rc']],
  ['/lck/fa', ['.brand']],
  ['/lck/builder', ['.brand']],
  ['/lck/schedule', ['.brand']],
  ['/lck/results', ['.brand', '.squad']],
  ['/lck/stove', ['.brand', '.sdates']],
  ['/lck/teams', ['.brand', '.tgrid']],
  ['/lck/game', ['.brand']],
  ['/lpl', ['.brand', '.soon-bar']],
  ['/about', ['.brand', '.pol-page']],
  ['/lck/summary', ['.brand', '.sgrid']],
  ['/lck/predict', ['.brand', '.acc']],
  ['/lck/contracts', ['.brand']],
  ['/lck/teams', ['.brand']],
  ['/privacy', ['.brand', '.pol-page']],
];

(async () => {
  const b = await chromium.launch();
  const fails = [], notes = [];
  for (const [size, opts] of Object.entries(SIZES)) {
    for (const scheme of ['light', 'dark']) {
      const ctx = await b.newContext({ ...opts, colorScheme: scheme });
      // 외부 글꼴·이미지는 막아서 네트워크 없이도 빨리 끝나게
      await ctx.route(u => !u.href.startsWith(B), r => r.abort());
      await ctx.addInitScript(s => { try { localStorage.setItem('theme', s); } catch (e) {} }, scheme);
      for (const [url, sels] of PAGES) {
        const p = await ctx.newPage();
        const tag = `${size}/${scheme} ${url}`;
        p.on('pageerror', e => fails.push(`${tag}: JS 오류 ${e.message}`));
        p.on('response', r => { if (r.url().startsWith(B) && r.status() >= 500) fails.push(`${tag}: ${r.status()} ${r.url()}`); });
        const res = await p.goto(B + url, { waitUntil: 'load' });
        if (!res || res.status() >= 400) fails.push(`${tag}: 응답 ${res && res.status()}`);
        for (const s of sels) if (!(await p.$(s))) fails.push(`${tag}: ${s} 없음`);
        const wide = await p.evaluate(() => document.documentElement.scrollWidth - innerWidth);
        if (wide > 2) fails.push(`${tag}: 가로 넘침 ${wide}px`);
        if (scheme === 'light' || url === '/lck') {
          await p.screenshot({ path: path.join(OUT, `${size}-${scheme}${url.replace(/\//g, '_')}.png`) });
        }
        await p.close();
      }
      await ctx.close();
    }
  }
  // API
  const ctx = await b.newContext();
  for (const u of ['/healthz', '/api/status', '/api/items?league=lck']) {
    const r = await ctx.request.get(B + u);
    if (r.status() !== 200) fails.push(`API ${u}: ${r.status()}`); else notes.push(`API ${u}: 200`);
  }
  await b.close();
  console.log(notes.join('\n'));
  console.log(`캡처: ${OUT}`);
  if (fails.length) { console.log(`실패 ${fails.length}건\n` + fails.join('\n')); process.exit(1); }
  console.log('실패 0건');
})();
