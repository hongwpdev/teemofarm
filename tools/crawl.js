// 사이트 전체 점검: 첫 화면부터 사이트 안의 링크를 끝까지 따라가며 모든 화면에서 같은 규칙을 확인.
//   node tools/crawl.js [주소=http://127.0.0.1:8099]
// 메뉴만 누르는 점검(flows.js)이 놓치는 '본문 속 링크로 들어간 화면'까지 봄. 규칙은 아래 PAGE_RULES·DATA_RULES.
// 화면 규칙: 응답 오류·자바스크립트 오류 / 시즌 고르기에 같은 해 두 번 / 시즌 칩과 고른 시즌이 다름 /
//   '기록을 보고 있어요' 안내가 기록이 아닌 화면에 뜸 / 메뉴·하위 메뉴의 선택 표시가 0개나 2개 /
//   화면에 undefined·NaN·null·{{ 가 보임 / 같은 id 두 번 / 사이트 이미지 깨짐 /
//   (휴대폰) 메뉴 글자가 두 줄로 꺾임 · 화면이 옆으로 넘침
// 데이터 규칙: /api/integrity(같은 사람이 FA·로스터에서 다른 말) / 같은 사람의 자리(감독·코치·포지션)가 화면마다 다름 /
//   같은 사람의 상태(발표·유력·확정·미정)와 행선지가 이적 시장·행선지 맞히기·로스터에서 다름
// 실패가 하나라도 있으면 종료 코드 1. flows.js 끝에서도 함께 돌아감(GitHub 점검에 포함).
const { chromium } = require('playwright');

const MAX_PAGES = 400;          // 한 번에 보는 화면 수 상한
const PER_PATH = 10;            // 같은 화면(경로)에서 주소 뒤쪽(?team= 등)만 다른 것은 이만큼만
const SKIP = /^\/(api|static|img|tlogo|ads\.txt|healthz)|\.(xml|txt|json|png|jpg|svg|ico)$/;

async function crawl(base, opts = {}) {
  const B = base.replace(/\/$/, '');
  const fails = [];
  const bad = (url, msg) => fails.push(`${msg} (${url.replace(B, '') || '/'})`);
  const b = opts.browser || await chromium.launch();
  const facts = [];                                   // 데이터 비교용: [url, nick, 자리, 팀, 상태, 어디]

  const keyOf = u => { const x = new URL(u); x.hash = ''; x.searchParams.sort(); return x.pathname + x.search; };
  const live = u => { const x = new URL(u, B); return !x.searchParams.get('season') && !x.searchParams.get('final'); };

  async function visit(ctx, url, phone) {
    const p = await ctx.newPage();
    const errs = [];
    p.on('pageerror', e => errs.push(e.message));
    p.on('dialog', d => { errs.push('알림창: ' + d.message()); d.dismiss().catch(() => {}); });
    let res;
    try { res = await p.goto(url, { waitUntil: 'load', timeout: 15000 }); } catch (e) { bad(url, '열리지 않음: ' + String(e.message).split('\n')[0]); await p.close(); return []; }
    await p.waitForTimeout(300);
    // 화면이 나중에 채우는 칸(독버섯 심기)이 있으면 다 그려질 때까지 조금 기다림
    if (await p.$('#tf')) await p.waitForSelector('#tf[data-ready]', { timeout: 4000 }).then(() => p.waitForTimeout(200)).catch(() => {});
    const st = res ? res.status() : 0;
    if (st >= 400) { bad(url, `응답 ${st}`); await p.close(); return []; }
    errs.forEach(e => bad(url, '자바스크립트 오류: ' + e));
    const r = await p.evaluate(() => {
      const out = { links: [], problems: [], facts: [] };
      const txt = s => (s || '').replace(/\s+/g, ' ').trim();
      for (const a of document.querySelectorAll('a[href]')) out.links.push(a.href);
      // 시즌 고르기
      const sel = document.querySelector('.ssel');
      if (sel) {
        const items = [...sel.querySelectorAll('li a')].map(a => ({ y: txt(a.childNodes[0] && a.childNodes[0].textContent), s: txt((a.querySelector('small') || {}).textContent), on: a.classList.contains('on') }));
        const ys = items.map(i => i.y);
        const dup = ys.filter((y, i) => ys.indexOf(y) !== i);
        if (dup.length) out.problems.push(`시즌 고르기에 같은 시즌이 두 번: ${dup.join(', ')}`);
        const on = items.filter(i => i.on);
        if (on.length > 1) out.problems.push(`시즌 고르기에 선택 표시가 ${on.length}개`);
        const chip = txt((sel.querySelector('summary b') || {}).textContent);
        if (on.length === 1 && chip !== on[0].y) out.problems.push(`시즌 칩은 '${chip}'인데 고른 시즌은 '${on[0].y}'`);
        const archive = /기록을 보고 있어요/.test(txt((document.querySelector('.archive-bar') || {}).textContent));
        if (archive && !(on[0] && on[0].s === '기록')) out.problems.push(`'기록을 보고 있어요' 안내가 기록이 아닌 화면에 뜸`);
        if (!archive && on[0] && on[0].s === '기록') out.problems.push(`지난 시즌 기록인데 '기록을 보고 있어요' 안내가 없음`);
      }
      // 메뉴·하위 메뉴 선택 표시
      const top = document.querySelectorAll('.top_tab a.on').length;
      // 미니게임·사이트 소개·준비 중 리그 화면은 메뉴에 없는 화면이라 선택 표시 0개가 맞음
      const sec = document.body.dataset.sec || '';
      const inMenu = ['news', 'fa', 'summary', 'predict', 'builder', 'stove', 'schedule', 'results', 'roster', 'contracts', 'teams'].includes(sec)
        && !document.querySelector('.soon-bar');
      if (document.querySelector('.top_tab') && (top > 1 || (inMenu && top === 0))) out.problems.push(`위 메뉴의 선택 표시가 ${top}개`);
      for (const nav of document.querySelectorAll('.view_tab.squad')) {
        const n = nav.querySelectorAll('a.on').length;
        if (n !== 1) out.problems.push(`하위 메뉴(${txt(nav.getAttribute('aria-label'))})의 선택 표시가 ${n}개`);
      }
      // 화면 글자
      const body = document.querySelector('main') ? document.querySelector('main').innerText : document.body.innerText;
      const m = body.match(/\b(undefined|NaN|null|None)\b|\{\{|\}\}/);
      if (m) out.problems.push(`화면에 '${m[0]}'가 보임: …${txt(body.slice(Math.max(0, m.index - 20), m.index + 20))}…`);
      // 같은 id
      const ids = [...document.querySelectorAll('[id]')].map(e => e.id);
      const did = [...new Set(ids.filter((x, i) => ids.indexOf(x) !== i))];
      if (did.length) out.problems.push(`같은 id가 여러 번: ${did.slice(0, 5).join(', ')}`);
      // 사이트 이미지
      for (const img of document.querySelectorAll('img')) {
        // /img/shroom.png는 라이엇 공식 아이콘을 서버가 받아 와서 주는 것(인터넷 없는 점검 환경에선 없음)이라 뺌
        const u = new URL(img.src);
        if (img.complete && img.naturalWidth === 0 && u.origin === location.origin && u.pathname !== '/img/shroom.png') out.problems.push(`이미지 깨짐: ${u.pathname}`);
      }
      // 데이터: 사람마다 자리·상태·행선지(화면이 data-pos·data-label·data-dest로 알려 줌)
      const where = e => e.closest('#falist') ? '이적 시장 목록' : e.closest('.vrow') ? '행선지 맞히기' : e.closest('.tf-card') ? '독버섯 심기'
        : e.closest('.rgrid') ? '로스터' : e.closest('[data-label]') ? '이동 보드' : '';
      for (const e of document.querySelectorAll('[data-nick]')) {
        const w = where(e);
        if (!w) continue;
        let label = '', dest = '';
        const box = e.matches('[data-label]') ? e : e.closest('[data-label]');
        if (box && w !== '로스터') { label = box.dataset.label || ''; dest = box.dataset.dest || ''; }
        if (w === '로스터') {            // 로스터 카드: 이름 바로 뒤의 표시(발표·유력)만 그 사람 것, 행선지는 그 카드 팀
          // 이름 바로 뒤의 표시만 그 사람 것: 다른 사람 줄(.subl)이 나오면 멈춤.
          // '➔ DK 이적 유력'(.rmo, 계약 중 선수가 다른 팀으로)은 그 팀이 행선지, 'i.rm'(유력·확정)은 이 카드 팀이 행선지
          let n = e.nextElementSibling, out = null;
          while (n && !n.matches('[data-nick]') && !n.matches('.subl')) {
            if (n.matches('.rmo')) { out = n; break; }
            if (n.matches('i.rm')) { label = txt(n.textContent); break; }
            n = n.nextElementSibling;
          }
          if (!out && !label && e.parentElement && e.parentElement.matches('.subl')) {
            const sub = e.parentElement;
            const o = sub.querySelector('.rmo'), i = sub.querySelector('i.rm');
            if (o) out = o; else if (i) label = txt(i.textContent);
          }
          const card = e.closest('[data-team]');
          if (out) { label = /확정/.test(out.textContent) ? '확정' : '유력'; dest = out.dataset.dest || ''; }
          else if (label) dest = card ? card.closest('.rc').dataset.team : '';
          if (label === '' ) continue;   // 계약된 선수 칸(표시 없음)은 비교하지 않음
        }
        out.facts.push([e.dataset.nick, e.dataset.pos || '', label, dest, w]);
      }
      // 휴대폰: 메뉴 글자 꺾임 · 옆으로 넘침
      if (innerWidth < 500) {
        for (const a of document.querySelectorAll('.top_tab a, .view_tab a, .ssel summary b, .lgsel summary b')) {
          const range = document.createRange(); range.selectNodeContents(a);
          const rs = [...range.getClientRects()].filter(r => r.width > 0).sort((x, y) => x.top - y.top);
          let lines = rs.length ? 1 : 0;
          for (let i = 1; i < rs.length; i++) if (rs[i].top >= rs[i - 1].bottom - 2) lines++;   // 앞 줄 아래에서 시작하면 새 줄
          if (lines > 1) out.problems.push(`휴대폰에서 '${txt(a.textContent)}' 글자가 두 줄로 꺾임`);
        }
        if (document.documentElement.scrollWidth > innerWidth + 2) out.problems.push(`휴대폰에서 화면이 옆으로 넘침(${document.documentElement.scrollWidth}px)`);
      }
      return out;
    }).catch(e => ({ links: [], problems: ['점검 실패: ' + e.message], facts: [] }));
    r.problems.forEach(m => bad(url, (phone ? '[휴대폰] ' : '') + m));
    if (!phone && live(url)) r.facts.forEach(f => facts.push([url.replace(B, ''), ...f]));
    await p.close();
    return r.links;
  }

  // 1) PC로 링크를 따라가며 모든 화면 모으기
  const pc = await b.newContext({ viewport: { width: 1280, height: 900 } });
  await pc.route(u => !u.href.startsWith(B), r => r.abort());
  const seen = new Set(), perPath = {}, queue = [B + '/lck'], pages = [];
  while (queue.length && pages.length < MAX_PAGES) {
    const batch = queue.splice(0, 4);
    const found = await Promise.all(batch.map(async u => { pages.push(u); return visit(pc, u, false); }));
    for (const l of found.flat()) {
      let x; try { x = new URL(l); } catch (e) { continue; }
      if (x.origin !== new URL(B).origin || SKIP.test(x.pathname)) continue;
      const k = keyOf(x.href);
      if (seen.has(k)) continue;
      seen.add(k);
      perPath[x.pathname] = (perPath[x.pathname] || 0) + 1;
      if (perPath[x.pathname] > PER_PATH) continue;
      queue.push(B + k);
    }
    seen.add(keyOf(batch[0]));
  }
  await pc.close();
  // 2) 같은 화면들을 휴대폰 크기로
  const ph = await b.newContext({ viewport: { width: 360, height: 780 }, isMobile: true, hasTouch: true });
  await ph.route(u => !u.href.startsWith(B), r => r.abort());
  for (let i = 0; i < pages.length; i += 4) await Promise.all(pages.slice(i, i + 4).map(u => visit(ph, u, true)));
  await ph.close();
  if (!opts.browser) await b.close();

  // 3) 데이터 정합성
  try {
    const j = await (await fetch(B + '/api/integrity')).json();
    (j.problems || []).forEach(m => fails.push('정합성: ' + m));
  } catch (e) { fails.push('정합성 점검(/api/integrity)을 못 읽음: ' + e.message); }
  const byNick = {};
  for (const [url, nick, pos, label, dest, w] of facts) (byNick[nick.toLowerCase()] = byNick[nick.toLowerCase()] || []).push({ url, nick, pos, label, dest, w });
  for (const fs of Object.values(byNick)) {
    const pos = [...new Set(fs.map(f => f.pos).filter(Boolean))];
    if (pos.length > 1) fails.push(`정합성: ${fs[0].nick}의 자리가 화면마다 다름: ` + pos.map(x => `${x}(${fs.find(f => f.pos === x).url})`).join(' / '));
    // 상태·행선지: 이적 시장 목록 · 이동 보드 · 행선지 맞히기 · 로스터가 같은 말을 하는지(같은 원본에서 나오므로 달라선 안 됨)
    const norm = x => ({ '이적 확정': '확정', '발표': '확정', '잔류 발표': '잔류', '잔류': '잔류', '잔류 유력': '잔류 유력' }[x] || x);   // (독버섯 판은 오피셜 기사를 '발표'로 적어 둠)
    const say = {};
    for (const f of fs) {
      if (!f.label || f.label === '미정') continue;
      const v = `${norm(f.label)}${f.dest ? '→' + f.dest.toUpperCase() : ''}`;
      (say[v] = say[v] || new Set()).add(f.w);
    }
    if (Object.keys(say).length > 1) fails.push(`정합성: ${fs[0].nick}의 상태가 화면마다 다름: ` + Object.entries(say).map(([v, ws]) => `${[...ws].join('·')}엔 '${v}'`).join(' / '));
  }
  return { fails: [...new Set(fails)], pages: pages.length };
}

module.exports = { crawl };

if (require.main === module) {
  (async () => {
    const { fails, pages } = await crawl(process.argv[2] || 'http://127.0.0.1:8099');
    if (fails.length) { console.log(`사이트 전체 점검 실패 ${fails.length}건 (화면 ${pages}개)\n` + fails.join('\n')); process.exit(1); }
    console.log(`사이트 전체 점검 실패 0건 (화면 ${pages}개 × PC·휴대폰)`);
  })();
}
