// 사용 흐름 점검: 실제로 눌러 보면서 "눌러야 터지는" · "써 본 사람만 겪는" 버그를 찾음.
//   node tools/flows.js [주소=http://127.0.0.1:8099]
// 두 사람으로 같은 흐름을 돌림
//   처음 온 사람: 브라우저 저장소가 비어 있음
//   써 본 사람: 내 팀·지난 시즌 선택·필터 기억·스포 방지·라이트 모드·자동 조회 등이 이미 켜져 있음
// 실패가 하나라도 있으면 종료 코드 1.
const { chromium } = require('playwright');
const B = (process.argv[2] || 'http://127.0.0.1:8099').replace(/\/$/, '');
const fails = [];
let who = '';
const bad = msg => fails.push(`[${who}] ${msg}`);

const PERSONAS = {
  '처음 온 사람': null,
  '써 본 사람': {
    local: { theme: 'light', spoiler: '1', 'myTeam:lck': 't1', lckAuto: '1', chatCid: 'flowtestbrowser0001',
             chatName: '티모0001', readIds: '[]', favs: '["Faker"]' },
    session: { 'qs:lck:fa': '?season=2025', 'qs:lck:schedule': '?season=2026&x=1', 'qs:lck:roster': '?season=2026',
               'qs:lck:news': '?team=t1&hot=0', fbarOpen: '1' },
  },
};

async function emptyPopup(p) {
  return p.evaluate(() => {
    const d = document.getElementById('dim');
    if (!d || !d.classList.contains('show')) return false;
    return ((d.querySelector('.pop') || d).innerText || '').trim().length < 5;
  });
}
const year = p => p.$eval('.ssel summary b', e => e.textContent.trim()).catch(() => '');
const pathOf = u => new URL(u, B).pathname;
const seasonOf = u => new URL(u, B).searchParams.get('season') || '';

async function afterAction(p, what) {
  await p.waitForTimeout(250);
  if (await emptyPopup(p)) bad(`${what}: 내용 없는 팝업이 떠서 화면만 어두워짐`);
}

async function click(p, sel, what) {
  const el = typeof sel === 'string' ? await p.$(sel) : sel;
  if (!el) { bad(`${what}: 누를 대상(${sel})이 없음`); return false; }
  const href = await el.getAttribute('href');
  try {
    if (href && !href.startsWith('#')) await Promise.all([p.waitForNavigation({ waitUntil: 'load', timeout: 5000 }).catch(() => {}), el.click({ timeout: 5000 })]);
    else await el.click({ timeout: 5000 });
  } catch (e) { bad(`${what}: 누를 수 없음 (${String(e.message).split('\n')[0]})`); return false; }
  await p.waitForLoadState('load').catch(() => {});
  await afterAction(p, what);
  return true;
}

// 메뉴(위 탭) + 각 메뉴의 하위 탭을 모두 눌러 봄. season이 있으면 그 시즌이 모든 화면에서 유지돼야 함
async function walkMenus(p, start, season) {
  await p.goto(B + start);
  const want = season ? String(season) : await year(p);
  const tops = await p.$$eval('.top_tab a', xs => xs.map(a => ({ sec: a.dataset.sec, label: a.textContent.trim() })));
  for (const t of tops) {
    await p.goto(B + start);
    const a = await p.$(`.top_tab a[data-sec="${t.sec}"]`);
    await click(p, a, `메뉴 '${t.label}'`);
    const url = p.url();
    if (season && seasonOf(url) !== want) bad(`${want} 기록을 보다가 '${t.label}'을 누르니 시즌이 '${seasonOf(url) || '지금'}'으로 바뀜 (${pathOf(url)})`);
    if (!season && seasonOf(url)) bad(`'${t.label}'을 누르니 고르지도 않은 ${seasonOf(url)} 시즌으로 감 (${pathOf(url)})`);
    const y = await year(p);
    if (y && y !== want) bad(`'${t.label}' 화면의 시즌 표시가 ${y} (다른 화면은 ${want})`);
    const on = await p.$eval('.top_tab a.on', e => e.textContent.trim()).catch(() => '');
    if (!on.startsWith(t.label.replace('HOT', ''))) bad(`'${t.label}'을 눌렀는데 선택된 메뉴가 '${on}'`);
    const subs = await p.$$eval('.view_tab.squad a', xs => xs.map(a => ({ href: a.getAttribute('href'), label: a.textContent.trim() })));
    const here = p.url();
    for (const s of subs) {
      await p.goto(here);
      const sa = await p.$(`.view_tab.squad a[href="${s.href}"]`);
      await click(p, sa, `'${t.label}' > '${s.label}'`);
      const su = p.url();
      if (pathOf(su) !== pathOf(s.href)) bad(`'${t.label}' > '${s.label}'을 눌렀는데 ${pathOf(su)}로 감`);
      if (season && seasonOf(su) !== want) bad(`${want} 기록에서 '${t.label}' > '${s.label}'을 누르니 시즌이 '${seasonOf(su) || '지금'}'`);
      if (!season && seasonOf(su)) bad(`'${t.label}' > '${s.label}'을 누르니 고르지도 않은 ${seasonOf(su)} 시즌으로 감`);
      const sy = await year(p);
      if (sy && sy !== want) bad(`'${t.label}' > '${s.label}' 화면의 시즌 표시가 ${sy} (다른 화면은 ${want})`);
    }
  }
}

// 화면 안의 팀 탭(소식·일정·결과): 누르면 고른 팀으로 바뀌고 팝업이 뜨면 안 됨
async function teamTabs(p, path) {
  await p.goto(B + path);
  const ks = (await p.$$eval('#tabs a[data-t]', xs => xs.map(a => a.dataset.t))).filter(k => k !== 'all').slice(0, 3);
  if (!ks.length) { bad(`${path}: 팀 탭이 없음`); return; }
  for (const k of ks) {
    const a = await p.$(`#tabs a[data-t="${k}"]`);
    await click(p, a, `${path} 팀 탭 '${k}'`);
    const on = await p.$eval('#tabs a.on', e => e.dataset.t).catch(() => '');
    if (on !== k) bad(`${path}: 팀 탭 '${k}'을 눌렀는데 '${on}'이 선택됨`);
  }
}

async function popups(p) {
  await p.goto(B + '/lck/fa');
  if (!(await p.$('.fa-row .nm >> visible=true'))) await click(p, '#tabs a[data-t="all"]', '이적·FA 전체 팀');   // 내 팀에 FA가 없으면 전체로
  if (await click(p, '.fa-row .nm >> visible=true', '이적·FA 선수 이름')) {
    if (!(await p.$eval('#dim', d => d.classList.contains('show')).catch(() => false))) bad('이적·FA: 선수 이름을 눌러도 프로필 팝업이 안 뜸');
    await p.keyboard.press('Escape'); await p.waitForTimeout(300);
    if (await p.$eval('#dim', d => d.classList.contains('show')).catch(() => false)) bad('이적·FA: ESC로 팝업이 안 닫힘');
  }
  await p.goto(B + '/lck/roster');
  if (await click(p, '.rc .pn[data-page] >> visible=true', '로스터 선수 이름')) {
    if (!(await p.$eval('#dim', d => d.classList.contains('show')).catch(() => false))) bad('로스터: 선수 이름을 눌러도 팝업이 안 뜸');
    await click(p, '#dim .x', '팝업 닫기');
    if (await p.$eval('#dim', d => d.classList.contains('show')).catch(() => false)) bad('로스터: 닫기 버튼으로 팝업이 안 닫힘');
  }
  await p.goto(B + '/lck/results');
  const mt = await p.$('.mt[data-id]');
  if (mt) await click(p, mt, '결과 경기 상세');
  await p.goto(B + '/lck');
  if (await click(p, 'a[data-pol="privacy"]', '개인정보처리방침')) {
    if (!(await p.$eval('#pol-privacy', d => d.open).catch(() => false))) bad('개인정보처리방침 팝업이 안 열림');
    await p.keyboard.press('Escape');
  }
}

async function toggles(p) {
  await p.goto(B + '/lck');
  const t0 = await p.evaluate(() => document.documentElement.dataset.theme);
  await click(p, '#thm', '테마 버튼');
  const t1 = await p.evaluate(() => document.documentElement.dataset.theme);
  if (t0 === t1) bad('테마 버튼을 눌러도 밝기가 안 바뀜');
  await p.goto(B + '/lck/fa');
  if ((await p.evaluate(() => document.documentElement.dataset.theme)) !== t1) bad('테마를 바꾼 뒤 다른 화면으로 가니 원래대로 돌아감');
  await click(p, '#thm', '테마 되돌리기');
  const s0 = await p.evaluate(() => document.documentElement.dataset.spoiler || '');
  await click(p, '#spo', '스포 방지 버튼');
  if (s0 === (await p.evaluate(() => document.documentElement.dataset.spoiler || ''))) bad('스포 방지 버튼을 눌러도 바뀌지 않음');
  await click(p, '#spo', '스포 방지 되돌리기');
}

async function memory(p) {
  await p.goto(B + '/lck?team=t1&hot=0');
  await click(p, '.top_tab a[data-sec="fa"]', '소식 → 스토브리그');
  await click(p, '.top_tab a[data-sec="news"]', '스토브리그 → 소식');
  const u = new URL(p.url());
  if (u.searchParams.get('team') !== 't1') bad(`소식에서 고른 팀(T1)이 다른 메뉴에 갔다 오니 사라짐 (${u.search || '없음'})`);
}

async function vote(p) {
  await p.goto(B + '/lck/predict');
  const pick = await p.$('.vrow .vpick >> visible=true');
  if (!pick) return;
  await click(p, pick, '행선지 [고르기]');
  if (!(await p.$eval('#vsheet', d => d.open).catch(() => false))) { bad('행선지 [고르기]를 눌러도 팀 고르는 창이 안 뜸'); return; }
  await click(p, '#vsheet .vopts button[data-c="hle"]', '행선지 팀 고르기');
  await p.waitForTimeout(500);
  if (await p.$eval('#vsheet', d => d.open).catch(() => false)) bad('팀을 골라도 창이 안 닫힘');
  const txt = await p.$eval('.vrow .vpick', e => e.textContent).catch(() => '');
  if (!txt.includes('HLE')) bad(`투표한 뒤에도 내 선택이 안 보임 ('${txt}')`);
}

(async () => {
  const b = await chromium.launch();
  for (const [name, seed] of Object.entries(PERSONAS)) {
    for (const [size, opts] of [['PC', { viewport: { width: 1280, height: 900 } }], ['휴대폰', { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true }]]) {
      who = `${name} · ${size}`;
      const ctx = await b.newContext(opts);
      await ctx.route(u => !u.href.startsWith(B), r => r.abort());
      if (seed) await ctx.addInitScript(s => {
        try {
          if (sessionStorage.getItem('__seeded')) return;
          Object.entries(s.local).forEach(([k, v]) => localStorage.setItem(k, v));
          Object.entries(s.session).forEach(([k, v]) => sessionStorage.setItem(k, v));
          sessionStorage.setItem('__seeded', '1');
        } catch (e) {}
      }, seed);
      const p = await ctx.newPage();
      p.on('pageerror', e => bad(`자바스크립트 오류: ${e.message} (${pathOf(p.url())})`));
      p.on('dialog', d => { bad(`알림창이 뜸: ${d.message()}`); d.dismiss().catch(() => {}); });
      await p.goto(B + '/lck');
      const archive = (await p.$$eval('.ssel li a', xs => xs.map(a => new URL(a.href).searchParams.get('season')).filter(Boolean)))[0];
      await walkMenus(p, '/lck', null);
      if (archive) await walkMenus(p, `/lck/roster?season=${archive}`, archive);
      await teamTabs(p, '/lck');
      await teamTabs(p, '/lck/results');
      await popups(p);
      await toggles(p);
      await memory(p);
      await vote(p);
      await ctx.close();
    }
  }
  await b.close();
  const uniq = [...new Set(fails)];
  if (uniq.length) { console.log(`흐름 점검 실패 ${uniq.length}건\n` + uniq.join('\n')); process.exit(1); }
  console.log('흐름 점검 실패 0건 (처음 온 사람·써 본 사람 × PC·휴대폰)');
})();
