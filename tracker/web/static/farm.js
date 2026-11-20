// 독버섯 심기(소식 화면 맨 위): 농장 상태바(7칸 미니 밭·등급·점수·연속 수확) + 판 카드(진행 중 / 결과 내역) + 숨은 황금 버섯.
// 서버가 첫 화면(빈 밭·판 목록·결과 내역)을 그려 두고(views.farm_block, 화면 밀림 없게), 이 파일은 같은 모양으로 다시 그리며
// 브라우저에 저장된 내 점수·심은 상태만 얹는다. 그림·판 데이터는 #tf-data(서버)에서 받음.
// 저장(localStorage 'teemofarm_lck_v1'): points · streak · plantedMushrooms[판] = { picked: 'O'|'X'(경기는 'A'|'B'), isUnderdog,
//   plantedAt, status: pending|won|lost, harvested } · goldenFoundDates · fieldLog(밭에 자란 순서 'n' 일반 · 'g' 황금)
// 규칙: 심기 전엔 참여 인원만, 심으면 민심 비율 공개 · 맞히면 +1(심는 순간 30% 미만 쪽이면 역배 +2) · 빗나가면 연속 수확 0 ·
//   맞힌 판은 수확할 때까지 '진행 중' 맨 위, 수확하면 '결과 내역'으로 · 황금 버섯 하루 한 번 +5
(function () {
  const box = document.getElementById("tf");
  if (!box) return;
  const KEY = "teemofarm_lck_v1";
  const S = (window.SPS && window.SPS.store) || { get: () => "", set: () => {} };
  const phone = () => window.matchMedia("(max-width: 640px)").matches;
  let init = {};
  try { init = JSON.parse((document.getElementById("tf-data") || {}).textContent || "{}") || {}; } catch (e) { init = {}; }
  const ART = init.art || { spr: {}, col: {} };

  // ── 저장값 ──
  function load() {
    let s = {};
    try { s = JSON.parse(S.get(KEY) || "{}") || {}; } catch (e) { s = {}; }
    return {
      points: Number.isFinite(s.points) ? s.points : 0,
      streak: Number.isFinite(s.streak) ? s.streak : 0,
      plantedMushrooms: s.plantedMushrooms && typeof s.plantedMushrooms === "object" ? s.plantedMushrooms : {},
      goldenFoundDates: Array.isArray(s.goldenFoundDates) ? s.goldenFoundDates : [],
      fieldLog: Array.isArray(s.fieldLog) ? s.fieldLog : [],
    };
  }
  let st = load();
  const save = () => S.set(KEY, JSON.stringify(st));
  const today = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };
  const tier = p => p >= 15 ? { label: "협곡의 황금농부", badge: "👑", next: 0 } : p >= 5 ? { label: "버섯 채집꾼", badge: "🍄", next: 15 - p } : { label: "새싹 농부", badge: "🌱", next: 5 - p };
  let cid = S.get("chatCid");
  if (!/^[A-Za-z0-9_-]{8,40}$/.test(cid || "")) {
    cid = Array.from({ length: 24 }, () => "abcdefghijklmnopqrstuvwxyz0123456789"[Math.floor(Math.random() * 36)]).join("");
    S.set("chatCid", cid);
  }

  // ── 도트 그림(서버 tracker/web/farm_art.py와 같은 데이터) ──
  function px(k, w) {
    const g = ART.spr[k] || [], W = (g[0] || "").length || 12, H = g.length || 12;
    let r = "";
    g.forEach((row, y) => [...row].forEach((ch, x) => { if (ch !== ".") r += `<rect x="${x}" y="${y}" width="1.02" height="1.02" fill="${ART.col[ch]}"/>`; }));
    return `<svg class="tf-px" viewBox="0 0 ${W} ${H}" width="${w}" height="${w * H / W}" shape-rendering="crispEdges" aria-hidden="true">${r}</svg>`;
  }
  const plot = (what, size, cls = "") => `<span class="tf-plot ${cls}" style="--s:${size}px">${what ? `<span class="tf-sp">${px(what, size * 0.72)}</span>` : ""}<span class="tf-ground">${px(what ? "tile" : "hole", size)}</span></span>`;
  const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // ── 상태바 ──
  function field() {
    const log = st.fieldLog.slice(-7);
    let h = "";
    for (let i = 0; i < 7; i++) h += log[i] ? plot(log[i] === "g" ? "gold" : "shroom", 28, log[i] === "g" ? "tf-gold" : "") : plot(null, 28);
    return h;
  }
  function whoText() {
    const t = tier(st.points), n = Math.min(7, st.fieldLog.length), basket = Math.max(0, st.fieldLog.length - 7);
    return `<span class="tf-tier">${t.badge} ${t.label}</span><small>${t.next ? `다음 등급까지 ${t.next}점 · ` : ""}<span class="tf-fcnt">밭 ${n}/7칸${basket ? ` · 바구니 ${basket}` : ""}</span></small>`;
  }
  function bar() {
    const found = st.goldenFoundDates.includes(today());
    return `<section class="card tf-bar" aria-label="내 버섯 농장">
<div class="tf-field" title="수확한 버섯이 밭에 자라요">${field()}</div>
<div class="tf-who">${whoText()}</div>
<div class="tf-num"><span><em class="tf-pts">${st.points}</em>농장 점수</span><span class="tf-stk"><em>${st.streak}</em>연속 수확</span><span title="${found ? "오늘 황금 버섯을 찾았어요" : "오늘의 황금 버섯이 화면 어딘가에 숨어 있어요"}"><em>${found ? px("gold", 20) : "🔍"}</em>황금 버섯</span></div></section>`;
  }

  // ── 판 ──
  let board = { open: init.open || [], mine: {}, done: init.done || [] }, more = false, tab = "open";
  const sides = it => it.kind === "rumor" ? ["o", "x"] : ["a", "b"];
  const sideName = (it, c) => it.kind === "rumor" ? c.toUpperCase() : (c === "a" ? it.a_short : it.b_short);
  const pickLabel = (it, p) => it.kind === "rumor" ? (p === "o" ? (it.id.endsWith(":s") ? "O 남는다" : "O 간다") : (it.id.endsWith(":s") ? "X 떠난다" : "X 안 간다")) : (p === "a" ? it.a_label : it.b_label);
  function title(it) {
    if (it.kind === "rumor") {
      const stay = it.id.endsWith(":s");
      return `<b>${esc(it.nick)} · ${stay ? `${esc(it.a_short)} 잔류?` : `${esc(it.a_short)} → ${esc(it.b_short)}`}</b>`;
    }
    return `<b>${esc(it.a_label)} vs ${esc(it.b_label)}</b>`;
  }
  function when(iso) { const d = new Date(iso); return isNaN(d) ? "" : `${d.getMonth() + 1}/${d.getDate()}`; }
  function source(it) {
    if (it.kind === "rumor") return `<span class="tf-src">${esc(it.tag || "유력")} · <a href="${esc(it.url)}" target="_blank" rel="noopener">${esc(it.outlet)} 기사 ↗</a></span>`;
    const d = new Date(it.published);
    return `<span class="tf-src">${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")} · ${esc(it.title)}</span>`;
  }
  // 민심 게이지: show=false면 참여 인원만(심기 전엔 비율 비공개)
  function tug(it, show) {
    const [p, q] = sides(it), n = it.n || 0;
    if (!show) return `<div class="tf-tug"><span class="tf-none">${n ? `${n}명 참여 중 · 심으면 민심 공개` : "아직 아무도 안 심었어요"}</span></div>`;
    const a = (it.tally || {})[p] || 0, b = (it.tally || {})[q] || 0, m = a + b;
    if (!m) return `<div class="tf-tug"><span class="tf-none">아직 아무도 안 심었어요</span></div>`;
    const pa = Math.round(100 * a / m), segs = phone() ? 10 : 20;
    let s = "";
    for (let i = 0; i < segs; i++) s += `<i class="${i < Math.round(pa * segs / 100) ? "a" : "b"}"></i>`;
    const minor = m >= 10 && (a / m < 0.3 ? p : b / m < 0.3 ? q : "");
    return `<div class="tf-tug"><div class="tf-tl"><span class="tf-pa">${esc(sideName(it, p))} ${pa}%</span><span class="tf-n">민심 ${m}명${minor && !it.result ? ` · <b class="tf-bonus">${esc(sideName(it, minor))} 역배 +2</b>` : ""}</span><span class="tf-pb">${esc(sideName(it, q))} ${100 - pa}%</span></div><span class="tf-gauge">${s}</span></div>`;
  }
  // 사이트 전체 점검(tools/crawl.js)이 다른 화면과 상태·행선지를 비교할 수 있게
  const facts = it => it.kind === "rumor" && !it.result ? ` data-nick="${esc(it.nick)}" data-label="${esc(it.tag || "")}" data-dest="${esc(it.b)}"` : "";

  // 진행 중 한 줄
  function openRow(it) {
    const mine = st.plantedMushrooms[it.id];
    let cls = "", ground = plot(null, 48, "tf-empty"), act;
    if (!mine) {
      if (!it.open) return "";
      act = `<div class="tf-act tf-ox">${sides(it).map((c, i) => `<button type="button" class="${i ? "" : "tf-o"}" data-plant="${esc(it.id)}" data-pick="${c}">${esc(pickLabel(it, c))}</button>`).join("")}</div>`;
    } else if (mine.status === "pending") {
      cls = "tf-pend"; ground = plot("shroom", 48);
      const wait = it.kind !== "rumor" ? "경기 결과 기다리는 중" : /발표/.test(it.tag || "") ? "발표 나옴 · 공식 반영 기다리는 중" : "공식 발표 기다리는 중";
      act = `<span class="tf-act tf-pst">${esc(pickLabel(it, mine.picked.toLowerCase()))}에 심음 · ${wait}</span>`;
    } else if (mine.status === "won" && !mine.harvested) {
      cls = "tf-won"; ground = plot("gold", 48);
      act = `<button type="button" class="tf-act tf-harvest" data-harvest="${esc(it.id)}">✨ 버섯 수확하기 +${mine.isUnderdog ? 2 : 1}</button>`;
    } else if (mine.status === "lost" && !mine.shown) {
      cls = "tf-lost"; ground = plot("burnt", 48) + `<span class="tf-smoke"></span><span class="tf-smoke b"></span><span class="tf-smoke c"></span>`;
      act = `<span class="tf-act tf-pst">펑! 독버섯 · 연속 수확 0</span>`;
    } else return "";
    return `<li class="${cls}" data-item="${esc(it.id)}"${facts(it)}>${ground}<div class="tf-q">${title(it)}${source(it)}</div>${tug(it, !!mine)}${act}</li>`;
  }
  // 결과 내역 한 줄: 모두에게 보이는 결과·최종 민심 + (심었던 사람만) 내 기록
  function verdict(it) {
    const n = it.n || 0, w = (it.tally || {})[it.result] || 0;
    if (!n) return `<span class="tf-act tf-verdict">참여 없음</span>`;
    const r = w / n;
    return r >= 0.5 ? `<span class="tf-act tf-verdict tf-v-major">민심 적중</span>` : r < 0.3 ? `<span class="tf-act tf-verdict tf-v-upset">역배 대이변!</span>` : `<span class="tf-act tf-verdict tf-v-minor">소수 적중</span>`;
  }
  function outcome(it) {
    if (it.kind !== "rumor") return `${esc(it.result === "a" ? it.a_short : it.b_short)} 승`;
    const stay = it.id.endsWith(":s");
    return it.result === "o" ? (stay ? `O · ${esc(it.a_short)} 잔류 확정` : `O · ${esc(it.b_short)} 이적 확정`) : (stay ? "X · 잔류 안 함" : `X · ${esc(it.b_short)}행 아님`);
  }
  function doneRow(it) {
    const mine = st.plantedMushrooms[it.id];
    let ground = plot("shroom", 40), me = "";
    if (mine && mine.status !== "pending") {
      const side = esc(sideName(it, mine.picked.toLowerCase()));
      if (mine.status === "won") { ground = plot("gold", 40); me = `<span class="tf-me-badge tf-me-won">내 선택: ${side} · ${mine.harvested ? `+${mine.isUnderdog ? 2 : 1}점 수확 완료` : "수확 대기(진행 중 탭)"}</span>`; }
      else { ground = plot("burnt", 40); me = `<span class="tf-me-badge tf-me-lost">내 선택: ${side} · 펑! 독버섯</span>`; }
    }
    return `<li class="tf-res" data-item="${esc(it.id)}">${ground}<div class="tf-q">${title(it)}<span class="tf-src">결과 ${outcome(it)} · ${when(it.resolved_at)}</span>${me}</div>${tug(it, true)}${verdict(it)}</li>`;
  }

  function card() {
    const mineIds = Object.keys(st.plantedMushrooms).filter(id => board.mine[id]);
    const seen = new Set(), items = [];
    const add = it => { if (it && !seen.has(it.id)) { seen.add(it.id); items.push(it); } };
    const m = id => st.plantedMushrooms[id];
    mineIds.filter(id => m(id).status === "won" && !m(id).harvested).forEach(id => add(board.mine[id]));   // 수확 대기는 맨 위
    mineIds.filter(id => m(id).status === "lost" && !m(id).shown).forEach(id => add(board.mine[id]));      // 펑! 한 번 보여 주고 결과 내역으로
    board.open.forEach(add);
    mineIds.filter(id => m(id).status === "pending").forEach(id => add(board.mine[id]));                    // 마감됐지만 결과 기다리는 내 판
    const rows = items.map(openRow).filter(Boolean);
    const done = board.done.map(doneRow);
    if (!rows.length && !done.length) return "";
    const season = board.open.some(it => it.kind === "match");
    const desc = season ? "경기 시작 10분 전까지 이길 팀 진영에 심어요. 맞히면 +1점, 30% 미만 소수 쪽이 맞으면 역배 +2점."
      : "유력 기사가 맞을지 O·X 밭에 버섯을 심어요. 심으면 민심이 공개되고, 공식 확정되면 결과가 나와요. 맞히면 +1점, 30% 미만 소수 쪽이면 역배 +2점.";
    const cut = more ? rows.length : phone() ? 2 : 4;          // 소식이 너무 밀리지 않게: 휴대폰 2개 · PC 4개, 나머지는 '더 보기'
    const openPanel = rows.length ? `<ul>${rows.slice(0, cut).join("")}</ul>${rows.length > cut ? `<button type="button" class="tf-more" data-more="1">더 보기 · 전체 ${rows.length}개</button>` : ""}`
      : `<p class="tf-emptymsg">지금 심을 판이 없어요. 새 유력 기사가 뜨면 생겨요.</p>`;
    const donePanel = done.length ? `<ul>${done.join("")}</ul>` : `<p class="tf-emptymsg">아직 결과가 난 판이 없어요.</p>`;
    return `<section class="card tf-card" aria-label="독버섯 심기"><div class="tf-head"><h3>독버섯 심기 <small>${season ? "오늘의 경기" : "스토브리그 편"}</small></h3>
<div class="tf-tabs" role="tablist"><button type="button" role="tab" data-tab="open" aria-selected="${tab === "open"}">진행 중 <b>${rows.length}</b></button><button type="button" role="tab" data-tab="done" aria-selected="${tab === "done"}">결과 내역 <b>${done.length}</b></button></div></div>
<p class="tf-desc">${desc}</p>
<div class="tf-panel" data-panel="open"${tab === "open" ? "" : " hidden"}>${openPanel}</div>
<div class="tf-panel" data-panel="done"${tab === "done" ? "" : " hidden"}>${donePanel}</div></section>`;
  }

  function paint() {
    box.innerHTML = bar() + card();
    box.querySelectorAll("li.tf-lost").forEach(li => {        // 빗나간 판: 처음 볼 때 흔들림 + 펑 → 그을린 독버섯
      const mm = st.plantedMushrooms[li.dataset.item];
      if (!mm || mm.shown) return;
      mm.shown = true; save();
      const sp = li.querySelector(".tf-sp"), burnt = sp ? sp.innerHTML : "";
      if (sp) sp.innerHTML = px("shroom", 48 * 0.72);
      li.classList.add("tf-boom");
      setTimeout(() => { if (sp) sp.innerHTML = burnt; }, 550);
    });
  }

  // 결과 대조: 서버 결과로 pending → won/lost
  function judge() {
    let changed = false;
    for (const [id, m] of Object.entries(st.plantedMushrooms)) {
      const it = board.mine[id];
      if (!it || m.status !== "pending" || !it.result) continue;
      m.status = it.result === String(m.picked || "").toLowerCase() ? "won" : "lost";
      if (m.status === "lost") st.streak = 0;
      changed = true;
    }
    if (changed) save();
  }

  function refresh() {
    const ids = Object.keys(st.plantedMushrooms).join(",");
    return fetch(`/api/farm?cid=${encodeURIComponent(cid)}&ids=${encodeURIComponent(ids)}`).then(r => r.json()).then(d => {
      board = { open: d.open || [], mine: d.mine || {}, done: d.done || [] };
      judge(); paint(); hideGold();
    }).catch(() => { paint(); hideGold(); }).finally(() => { box.dataset.ready = "1"; });
  }

  // ── 연출 ──
  function setPoints() {
    const pts = box.querySelector(".tf-pts"); if (pts) pts.textContent = st.points;
    const stk = box.querySelector(".tf-stk em"); if (stk) stk.textContent = st.streak;
    const who = box.querySelector(".tf-who"); if (who) who.innerHTML = whoText();
    bump(".tf-pts");
  }
  function bump(sel) { const e = box.querySelector(sel); if (!e) return; e.classList.remove("tf-bump"); void e.offsetWidth; e.classList.add("tf-bump"); }
  function sparks(host, text) {
    const dirs = [[-26, -18], [24, -20], [-30, 6], [30, 4], [-12, -30], [14, -30], [0, -36], [-20, 18]];
    host.insertAdjacentHTML("beforeend", `<span class="tf-float">${text}</span>` + dirs.map(([x, y]) => `<i class="tf-spark" style="--dx:${x}px;--dy:${y}px"></i>`).join(""));
    setTimeout(() => host.querySelectorAll(".tf-float,.tf-spark").forEach(e => e.remove()), 1300);
  }
  function growField(kind) {
    st.fieldLog.push(kind); save();
    const f = box.querySelector(".tf-field"); if (!f) return;
    f.innerHTML = field();
    const all = f.querySelectorAll(".tf-plot"), i = Math.min(7, st.fieldLog.length) - 1;
    if (all[i]) all[i].classList.add("tf-in");
    const c = box.querySelector(".tf-fcnt"); if (c) c.textContent = `밭 ${Math.min(7, st.fieldLog.length)}/7칸${st.fieldLog.length > 7 ? ` · 바구니 ${st.fieldLog.length - 7}` : ""}`;
  }
  function toast(msg) {
    const t = document.createElement("div"); t.className = "tf-toast"; t.textContent = msg;
    const b = box.querySelector(".tf-bar");
    if (b) { const r = b.getBoundingClientRect(); t.style.top = Math.max(8, r.bottom + 8) + "px"; }
    document.body.appendChild(t); setTimeout(() => t.remove(), 1800);
  }

  box.addEventListener("click", e => {
    const tb = e.target.closest("[data-tab]");
    if (tb) { tab = tb.dataset.tab; paint(); return; }
    const pb = e.target.closest("[data-plant]");
    if (pb) {
      const id = pb.dataset.plant, pick = pb.dataset.pick;
      if (st.plantedMushrooms[id]) return;
      const lock = on => box.querySelectorAll(`[data-plant="${CSS.escape(id)}"]`).forEach(b => { b.disabled = on; });
      lock(true);
      fetch("/api/farm/plant", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ item: id, pick, cid }) })
        .then(r => r.json()).then(d => {
          if (!d.ok && d.msg !== "이미 심었어요") { toast(d.msg || "지금은 심을 수 없어요"); lock(false); return; }
          st.plantedMushrooms[id] = { picked: pick.toUpperCase(), isUnderdog: !!d.bonus, plantedAt: new Date().toISOString(), status: "pending", harvested: false };
          save();
          const it = board.open.find(x => x.id === id);
          if (it) { if (d.tally) { it.tally = d.tally; it.n = Object.values(d.tally).reduce((x, y) => x + y, 0); } board.mine[id] = it; }
          paint();
          const pl = box.querySelector(`li[data-item="${CSS.escape(id)}"] .tf-plot`); if (pl) pl.classList.add("tf-in");
          if (d.bonus) toast("역배에 심었어요! 맞히면 +2점");
        }).catch(() => { toast("지금은 심을 수 없어요. 잠시 뒤에 다시 눌러 주세요"); lock(false); });
      return;
    }
    const hb = e.target.closest("[data-harvest]");
    if (hb) {
      const id = hb.dataset.harvest, m = st.plantedMushrooms[id];
      if (!m || m.status !== "won" || m.harvested) return;            // 두 번 받지 않게
      const add = m.isUnderdog ? 2 : 1;
      m.harvested = true; st.points += add; st.streak += 1; save();
      const li = hb.closest("li"), ground = li.querySelector(".tf-plot");
      hb.outerHTML = `<span class="tf-act tf-pst tf-got">수확 완료 ✓ +${add}</span>`;
      if (ground) sparks(ground, "+" + add);
      setPoints();
      setTimeout(() => growField("n"), 450);
      setTimeout(() => { if (tab === "open") paint(); }, 1400);         // 연출이 끝나면 결과 내역으로 옮김
      return;
    }
    if (e.target.closest("[data-more]")) { more = true; paint(); }
  });

  // ── 숨은 황금 버섯(하루 한 번) ──
  // 숨을 자리: 오른쪽 스토브리그 현황·팀 로스터 칸, 리그 안내 줄, 휴대폰 스토브리그 숫자 줄, 소식 목록 위(광고 칸은 빼고)
  const SPOTS = [".rail .rail-stove", ".rail > .card:not(.aff):not(.rail-stove)", ".lguide > summary", "nav.stove", ".layout > div > .card:not(.fbar):not(.aff):not(.tf-bar):not(.tf-card)"];
  function hideGold() {
    document.querySelectorAll(".tf-goldspot").forEach(e => e.remove());
    const d = today();
    if (st.goldenFoundDates.includes(d)) return;
    const shown = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(e).visibility !== "hidden"; };
    const cand = SPOTS.map(s => document.querySelector(s)).filter(e => e && e.tagName !== "DETAILS" && shown(e) && !e.closest(".aff"));
    if (!cand.length) return;
    let h = 0; for (const ch of d + cid) h = (h * 31 + ch.charCodeAt(0)) >>> 0;   // 날마다·사람마다 다른 자리
    const g = document.createElement("button");
    g.type = "button"; g.className = "tf-goldspot"; g.title = "어? 뭔가 반짝여요"; g.setAttribute("aria-label", "숨은 황금 버섯");
    g.innerHTML = px("gold", 18);
    // 고른 자리에서 안 보이면(잘림·숨김) 다음 자리로
    for (let k = 0; k < cand.length; k++) {
      const host = cand[(h + k) % cand.length];
      if (getComputedStyle(host).position === "static") host.style.position = "relative";
      host.appendChild(g);
      const r = g.getBoundingClientRect(), hr = host.getBoundingClientRect();
      if (r.width > 0 && r.top >= hr.top - 1 && r.bottom <= hr.bottom + 1 && document.elementFromPoint && shown(g)) break;
      g.remove();
    }
    if (!g.isConnected) return;
    g.addEventListener("click", ev => {
      ev.preventDefault(); ev.stopPropagation();
      if (st.goldenFoundDates.includes(today())) return;               // 하루 한 번
      st.goldenFoundDates.push(today()); st.points += 5; save();
      const r = g.getBoundingClientRect(), f = box.querySelector(".tf-field");
      const slots = f ? f.querySelectorAll(".tf-plot") : [];
      const target = slots[Math.min(6, st.fieldLog.length)] || f;
      const fly = document.createElement("div"); fly.className = "tf-fly"; fly.innerHTML = px("gold", 22);
      fly.style.left = r.left + "px"; fly.style.top = r.top + "px"; document.body.appendChild(fly); g.remove();
      const t = target ? target.getBoundingClientRect() : r;
      requestAnimationFrame(() => requestAnimationFrame(() => { fly.style.left = (t.left + 3) + "px"; fly.style.top = (t.top + 2) + "px"; fly.style.transform = "scale(1.1) rotate(360deg)"; }));
      setTimeout(() => {
        fly.remove(); growField("g");
        setPoints();
        const gi = box.querySelector(".tf-num span:last-child em"); if (gi) gi.innerHTML = px("gold", 20);
        toast("✨ 황금 버섯 발견! +5점");
      }, 750);
    });
  }

  paint();
  refresh();
})();
