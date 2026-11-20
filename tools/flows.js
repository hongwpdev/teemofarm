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
             chatName: '티모0001', readIds: '[]', favs: '["Faker"]',
             // 독버섯 심기: 결과가 난 판(dev_server의 'rm:DevShroom:t1:m')에 O로 심어 둔 사람
             teemofarm_lck_v1: JSON.stringify({ points: 3, streak: 1, goldenFoundDates: [], fieldLog: ['n', 'n'],
               plantedMushrooms: { 'rm:DevShroom:t1:m': { picked: 'O', isUnderdog: false, plantedAt: '2026-01-01T00:00:00Z', status: 'pending', harvested: false } } }) },
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
  const wantLabel = season ? `${season} 시즌` : want;
  const tops = await p.$$eval('.top_tab a', xs => xs.map(a => ({ sec: a.dataset.sec, label: a.textContent.trim() })));
  for (const t of tops) {
    await p.goto(B + start);
    const a = await p.$(`.top_tab a[data-sec="${t.sec}"]`);
    await click(p, a, `메뉴 '${t.label}'`);
    const url = p.url();
    if (season && seasonOf(url) !== want) bad(`${want} 기록을 보다가 '${t.label}'을 누르니 시즌이 '${seasonOf(url) || '지금'}'으로 바뀜 (${pathOf(url)})`);
    if (!season && seasonOf(url)) bad(`'${t.label}'을 누르니 고르지도 않은 ${seasonOf(url)} 시즌으로 감 (${pathOf(url)})`);
    const y = await year(p);
    if (y && y !== wantLabel) bad(`'${t.label}' 화면의 시즌 표시가 ${y} (다른 화면은 ${want})`);
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
      if (sy && sy !== wantLabel) bad(`'${t.label}' > '${s.label}' 화면의 시즌 표시가 ${sy} (다른 화면은 ${want})`);
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
  if (!p.url().includes('/predict')) return;                    // 행선지 맞히기가 꺼져 있으면(config.FEATURES) 팀별로 옮겨 감
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

// 독버섯 심기: 심기 → 잠김 / (써 본 사람) 결과 난 판 수확은 한 번만 / 황금 버섯은 하루 한 번
// 소식 보기·팀·기간을 바꾸면 소식 칸만 바뀜(새로 불러오지 않음): 주소·뒤로 가기·스크롤·[조회] 단추가 그대로인지
async function swap(p) {
  await p.goto(B + '/lck?team=all');
  await p.waitForSelector('#tf[data-ready]', { timeout: 5000 }).catch(() => {});
  await p.evaluate(() => { window.__keep = 1; });
  const tab = p.locator('.view_tab a', { hasText: '스토브리그' });
  await tab.scrollIntoViewIfNeeded(); await p.evaluate(() => window.scrollBy(0, 100));
  const y0 = await p.evaluate(() => scrollY);
  await tab.click();
  const ok = await p.waitForFunction(() => location.search.includes('hot=2') && !document.querySelector('.layout.is-loading'), null, { timeout: 5000 }).catch(() => null);
  if (!ok) { bad('소식 보기를 바꿨는데 주소가 안 바뀜'); return; }
  const s = await p.evaluate(() => ({ keep: window.__keep, y: scrollY, on: (document.querySelector('.view_tab a.on') || {}).textContent, go: !!document.getElementById('go') }));
  if (s.keep !== 1) bad('소식 보기를 바꿨는데 화면 전체를 새로 불러옴(소식 칸만 바뀌어야 함)');
  if (Math.abs(s.y - y0) > 2) bad(`소식 보기를 바꿨는데 스크롤이 ${y0} → ${s.y}로 튐`);
  if (s.on !== '스토브리그') bad(`바꾼 뒤 보기 표시가 '${s.on}'`);
  if (!s.go) bad('바꾼 뒤 [조회] 단추가 사라짐');
  await p.goBack();
  const back = await p.waitForFunction(() => !location.search.includes('hot=2') && !document.querySelector('.layout.is-loading') &&
    (document.querySelector('.view_tab a.on') || {}).textContent === '전체', null, { timeout: 5000 }).catch(() => null);
  if (!back) bad('뒤로 가기로 이전 소식 보기가 안 돌아옴');
}

async function farm(p, seeded) {
  const pts = async () => +(await p.$eval('.tf-pts', e => e.textContent).catch(() => 'NaN'));
  await p.goto(B + '/lck');
  if (!(await p.waitForSelector('#tf .tf-bar', { timeout: 5000 }).catch(() => null))) { bad('독버섯 심기 상태바가 안 보임'); return; }
  await p.waitForSelector('#tf[data-ready]', { timeout: 5000 }).catch(() => bad('독버섯 심기가 서버 판 목록을 못 받아 옴'));
  if (seeded) {
    const h = await p.waitForSelector('[data-harvest]', { timeout: 5000 }).catch(() => null);
    if (!h) bad('결과가 난 판인데 [버섯 수확하기]가 안 보임');
    else {
      const before = await pts();
      await h.click(); await p.waitForTimeout(400);
      if (await pts() !== before + 1) bad(`수확했는데 점수가 ${before} → ${await pts()}`);
      if (await p.$('[data-harvest]')) bad('수확한 뒤에도 수확 버튼이 남아 있음');
      // 스킨 해금 축하: 점수 3으로 처음 왔을 때 정찰부대가 이미 축하됐고, 이번 수확(최고 연속 2)으로 오소리 티모 배너가 떠야 함
      const un = await p.waitForSelector('#tf-unlock:not([hidden])', { timeout: 2000 }).catch(() => null);
      const unText = un ? await un.innerText() : '';
      if (!/오소리 티모 해금/.test(unText)) bad(`수확으로 새 스킨이 열렸는데 해금 배너가 안 뜸 ('${unText.replace(/\s+/g, ' ')}')`);
      const unl = await p.evaluate(() => JSON.parse(localStorage.getItem('teemofarm_lck_v1')).unlocked || []);
      if (!unl.includes(2) || !unl.includes(3)) bad(`해금 축하 기록이 이상함: ${JSON.stringify(unl)}`);
      await p.reload(); await p.waitForSelector('#tf[data-ready]', { timeout: 5000 }).catch(() => {}); await p.waitForTimeout(300);
      if (await p.$('[data-harvest]')) bad('다시 들어오니 같은 버섯을 또 수확할 수 있음(중복 수령)');
      if (await pts() !== before + 1) bad(`다시 들어오니 점수가 ${await pts()} (수확 뒤 ${before + 1})`);
      if (await p.$('#tf-unlock:not([hidden])')) bad('이미 축하한 스킨인데 다시 들어오니 해금 배너가 또 뜸');
      // 수확한 판은 '결과 내역'으로: 모두의 결과 + 내 기록
      await click(p, '#tf [data-tab="done"]', "독버섯 심기 '결과 내역' 탭");
      const mine = await p.$eval('#tf [data-panel="done"] li[data-item="rm:DevShroom:t1:m"]', e => e.innerText).catch(() => '');
      if (!/내 선택: O · \+1점 수확 완료/.test(mine)) bad(`결과 내역에 내 수확 기록이 안 보임 ('${mine.replace(/\s+/g, ' ').slice(0, 60)}')`);
      if (await p.$eval('#tf [data-panel="open"]', e => !e.hidden).catch(() => true)) bad("'결과 내역'을 눌렀는데 진행 중 판이 그대로 보임");
      await click(p, '#tf [data-tab="open"]', "독버섯 심기 '진행 중' 탭");
    }
  }
  const pb = await p.waitForSelector('.tf-card [data-plant]', { timeout: 5000 }).catch(() => null);
  if (!pb) bad('심을 수 있는 판이 없음');
  else {
    const id = await pb.getAttribute('data-plant');
    if (await p.$(`li[data-item="${id}"] .tf-gauge`)) bad('심기 전인데 민심 비율이 보임(심은 뒤에만 공개)');
    await pb.click(); await p.waitForTimeout(600);
    if (!(await p.$(`li[data-item="${id}"] .tf-gauge`))) bad('심었는데 민심 비율 게이지가 안 보임');
    const li = await p.$(`li[data-item="${id}"]`);
    if (!li || !(await li.evaluate(e => e.classList.contains('tf-pend')))) bad('심었는데 "심음 · 기다리는 중"으로 안 바뀜');
    if (await p.$(`[data-plant="${id}"]`)) bad('심은 판에 아직 심기 버튼이 남아 있음');
  }
  // 독버섯 판 '더 보기'로 펼치면 '접기'로 다시 접을 수 있어야 함
  if (await p.$('.tf-card [data-panel="open"] [data-more]')) {
    const count = () => p.$$eval('.tf-card [data-panel="open"] > ul > li', xs => xs.filter(x => x.offsetParent).length);
    const before = await count();
    await click(p, '.tf-card [data-more]', "독버섯 판 '더 보기'");
    const all = await count();
    if (!(all > before)) bad(`'더 보기'를 눌러도 판이 늘지 않음 (${before} → ${all})`);
    if (!(await p.$('.tf-card [data-less]'))) bad("독버섯 판을 펼친 뒤 '접기' 버튼이 없음");
    else {
      await click(p, '.tf-card [data-less]', "독버섯 판 '접기'");
      if (await count() !== before) bad(`'접기'를 눌러도 처음 개수(${before})로 안 돌아감 (${await count()})`);
      if (!(await p.$('.tf-card [data-more]'))) bad("접은 뒤 '더 보기' 버튼이 다시 안 보임");
    }
  }
  const g = await p.$('.tf-goldspot');
  if (!g) bad('오늘의 황금 버섯이 화면에 없음');
  else {
    const before = await pts();
    await g.click({ force: true }); await p.waitForTimeout(1100);
    if (await pts() !== before + 5) bad(`황금 버섯을 찾았는데 점수가 ${before} → ${await pts()}`);
    await p.reload(); await p.waitForSelector('#tf[data-ready]', { timeout: 5000 }).catch(() => {}); await p.waitForTimeout(300);
    if (await p.$('.tf-goldspot')) bad('황금 버섯을 찾은 날인데 또 나옴');
  }
  // 소식 목록의 '이 소식 O/X 심기 ↑' → 위 독버섯 심기 칸의 그 판(접혀 있던 판도 펼쳐서)으로
  const jumps = await p.$$('[data-farm-jump]');
  if (!jumps.length) bad('열린 유력 판의 기사에 O/X 심기 바로가기가 없음');
  else {
    const j = jumps[jumps.length - 1], id = await j.getAttribute('data-farm-jump');
    await j.scrollIntoViewIfNeeded(); await j.click(); await p.waitForTimeout(900);
    const ok = await p.evaluate(id => { const li = document.querySelector(`#tf li[data-item="${CSS.escape(id)}"]`); if (!li) return false;
      const r = li.getBoundingClientRect(); return r.top >= 0 && r.bottom <= innerHeight; }, id);
    if (!ok) bad(`O/X 심기 바로가기를 눌렀는데 그 판(${id})이 화면에 안 보임`);
  }
  // 티모 스킨 도감: 열리고, 잠긴 스킨은 못 누르고, 바깥을 누르면 닫힘
  await p.click('.tf-skin'); await p.waitForTimeout(200);
  const sk = await p.evaluate(() => ({ open: !!document.querySelector('.tf-skins:not([hidden])'), n: document.querySelectorAll('[data-skin]').length,
    lockedOk: [...document.querySelectorAll('.tf-skin-it.tf-lock')].every(b => b.disabled), on: document.querySelectorAll('.tf-skin-it.tf-on').length }));
  if (!sk.open) bad('티모 스킨 도감이 안 열림');
  else {
    if (sk.n !== 16 || sk.on !== 1 || !sk.lockedOk) bad(`스킨 도감 이상: 스킨 ${sk.n}개 · 쓰는 중 ${sk.on}개 · 잠긴 것 눌림 ${!sk.lockedOk}`);
    await p.mouse.click(5, 5); await p.waitForTimeout(200);
    if (await p.$('.tf-skins:not([hidden])')) bad('바깥을 눌러도 스킨 도감이 안 닫힘');
  }
  // 기록 공유: 수확 카드(그림) 창이 열리고, 그림이 그려져 있고, 닫힘
  await p.click('.tf-share'); await p.waitForTimeout(300);
  const shot = await p.evaluate(() => { const d = document.getElementById('tf-shot'); const im = d && d.querySelector('img');
    return { open: !!(d && d.open), img: !!(im && im.src.startsWith('data:image/png') && im.naturalWidth === 1080) }; });
  if (!shot.open) bad('기록 공유를 눌렀는데 수확 카드 창이 안 열림');
  else {
    if (!shot.img) bad('수확 카드 그림이 비어 있음');
    await p.click('[data-shot="close"]'); await p.waitForTimeout(200);
    if (await p.evaluate(() => document.getElementById('tf-shot').open)) bad('수확 카드 창의 닫기가 안 됨');
  }
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
      // 시즌 고르기의 모든 시즌(예정·지난 기록)마다 메뉴를 다 눌러 봄
      const picks = await p.$$eval('.ssel li a', xs => xs.map(a => new URL(a.href).searchParams.get('season')).filter(Boolean));
      await walkMenus(p, '/lck', null);
      for (const y of [...new Set(picks)]) await walkMenus(p, `/lck/roster?season=${y}`, y);
      await teamTabs(p, '/lck');
      await teamTabs(p, '/lck/results');
      await popups(p);
      await toggles(p);
      await memory(p);
      await vote(p);
      await farm(p, !!seed);
      await swap(p);
      await ctx.close();
    }
  }
  // 사이트 전체: 본문 속 링크까지 모든 화면을 따라가며 같은 규칙 + 데이터 정합성(tools/crawl.js)
  const site = await require('./crawl').crawl(B, { browser: b });
  site.fails.forEach(m => fails.push(`[사이트 전체] ${m}`));
  await b.close();
  const uniq = [...new Set(fails)];
  if (uniq.length) { console.log(`흐름 점검 실패 ${uniq.length}건\n` + uniq.join('\n')); process.exit(1); }
  console.log(`흐름 점검 실패 0건 (처음 온 사람·써 본 사람 × PC·휴대폰 + 사이트 전체 화면 ${site.pages}개)`);
})();
