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
      best: Number.isFinite(s.best) ? s.best : (Number.isFinite(s.streak) ? s.streak : 0),   // 최고 연속 수확(수확 카드용)
      quiz: s.quiz && typeof s.quiz === "object" ? s.quiz : {},                                // 오늘의 로스터 퀴즈 {date, pick, ok}
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
<div class="tf-num"><span><em class="tf-pts">${st.points}</em>농장 점수</span><span class="tf-stk"><em>${st.streak}</em>연속 수확</span><span title="${found ? "오늘 황금 버섯을 찾았어요" : "오늘의 황금 버섯이 화면 어딘가에 숨어 있어요"}"><em>${found ? px("gold", 20) : "🔍"}</em>황금 버섯</span><button type="button" class="tf-share" title="내 농장 수확 카드를 그림으로 저장하거나 글로 복사해요"><em>📋</em>기록 공유</button></div></section>`;
  }

  // ── 판 ──
  let board = { open: init.open || [], mine: {}, done: init.done || [], quiz: init.quiz || null }, more = false, tab = "open";
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
    // 격전지: 10명 이상이 45~55%로 갈린 판(심은 뒤·결과 내역에서만 보임 — 심기 전엔 비율 자체가 비공개). 쏠린 판은 '역배 +2'가 이미 알려 줌
    const hot = m >= 10 && pa >= 45 && pa <= 55;
    return `<div class="tf-tug"><div class="tf-tl"><span class="tf-pa">${esc(sideName(it, p))} ${pa}%</span><span class="tf-n">민심 ${m}명${minor && !it.result ? ` · <b class="tf-bonus">${esc(sideName(it, minor))} 역배 +2</b>` : hot ? ` · <b class="tf-hot">🔥 격전지</b>` : ""}</span><span class="tf-pb">${esc(sideName(it, q))} ${100 - pa}%</span></div><span class="tf-gauge">${s}</span></div>`;
  }
  // 사이트 전체 점검(tools/crawl.js)이 다른 화면과 상태·행선지를 비교할 수 있게
  const facts = it => it.kind === "rumor" && !it.result && !/무산/.test(it.tag || "") ? ` data-nick="${esc(it.nick)}" data-label="${esc(it.tag || "")}" data-dest="${esc(it.b)}"` : "";

  // 진행 중 한 줄
  function openRow(it) {
    const mine = st.plantedMushrooms[it.id];
    let cls = "", ground = plot(null, 48, "tf-empty"), act;
    if (!mine) {
      if (!it.open) return "";
      act = `<div class="tf-act tf-ox">${sides(it).map((c, i) => `<button type="button" class="${i ? "" : "tf-o"}" data-plant="${esc(it.id)}" data-pick="${c}">${esc(pickLabel(it, c))}</button>`).join("")}</div>`;
    } else if (mine.status === "pending") {
      cls = "tf-pend"; ground = plot("shroom", 48);
      const wait = it.kind !== "rumor" ? "경기 결과 기다리는 중" : /발표/.test(it.tag || "") ? "발표 나옴 · 공식 반영 기다리는 중" : /무산/.test(it.tag || "") ? "무산 보도 · 공식 반영 기다리는 중" : "공식 발표 기다리는 중";
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
  // 심을 판이 없는 날의 '오늘의 로스터 퀴즈'(서버 views._tf_quiz와 같은 모양 + 내가 푼 기록)
  function quizBox(q) {
    const mine = st.quiz.date === q.date ? st.quiz : null;
    const btns = q.options.map((o, i) => {
      const cls = mine ? (i === q.answer ? "tf-qz-ok" : i === mine.pick ? "tf-qz-no" : "") : "";
      return `<button type="button" data-quiz-pick="${i}"${cls ? ` class="${cls}"` : ""}${mine ? " disabled" : ""}>${esc(o)}</button>`;
    }).join("");
    const msg = !mine ? "심을 판이 없는 날엔 하루 한 문제 · 맞히면 버섯 +1"
      : mine.ok ? "정답! 버섯 +1 수확 · 내일 새 문제가 나와요" : `아쉬워요. 정답은 ${esc(q.options[q.answer])} · 내일 새 문제가 나와요`;
    return `<div class="tf-quiz" data-quiz="${esc(q.id)}"><p class="tf-qz-q"><span class="tf-qz-tag">🎯 오늘의 로스터 퀴즈</span><b>${esc(q.question)}</b></p><div class="tf-qz-opts">${btns}</div><p class="tf-qz-msg">${msg}</p></div>`;
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
    return `<li class="tf-res${it.kind === "match" ? " tf-m" : ""}" data-item="${esc(it.id)}">${ground}<div class="tf-q">${title(it)}<span class="tf-src">결과 ${outcome(it)} · ${when(it.resolved_at)}</span>${me}</div>${tug(it, true)}${verdict(it)}</li>`;
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
    if (!rows.length && !done.length && !board.quiz) return "";
    const season = board.open.some(it => it.kind === "match");
    const desc = season ? "경기 시작 10분 전까지 이길 팀 진영에 심어요. 맞히면 +1점, 30% 미만 소수 쪽이 맞으면 역배 +2점(10명 이상 참여한 판)."
      : "유력 기사가 맞을지 O·X 밭에 버섯을 심어요. 심으면 민심이 공개되고, 공식 확정되면 결과가 나와요. 맞히면 +1점, 30% 미만 소수 쪽이면 역배 +2점(10명 이상 참여한 판).";
    const cut = more ? rows.length : phone() ? 2 : 4;          // 소식이 너무 밀리지 않게: 휴대폰 2개 · PC 4개, 나머지는 '더 보기'
    const openPanel = rows.length ? `<ul>${rows.slice(0, cut).join("")}</ul>${rows.length > cut ? `<button type="button" class="tf-more" data-more="1">더 보기 · 전체 ${rows.length}개</button>` : ""}`
      : board.quiz && !board.open.length ? quizBox(board.quiz) : `<p class="tf-emptymsg">지금 심을 판이 없어요. 새 유력 기사가 뜨면 생겨요.</p>`;
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
      board = { open: d.open || [], mine: d.mine || {}, done: d.done || [], quiz: d.quiz || null };
      // 저장값이 지워졌어도 이 브라우저(같은 번호)가 열린 판에 심은 쪽은 서버 기록으로 되살림
      let back = false;
      for (const [id, pick] of Object.entries(d.my_picks || {})) {
        if (st.plantedMushrooms[id]) continue;
        st.plantedMushrooms[id] = { picked: String(pick).toUpperCase(), isUnderdog: false, plantedAt: "", status: "pending", harvested: false };
        board.mine[id] = board.open.find(x => x.id === id); back = true;
      }
      if (back) save();
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
    const sp = e.target.closest("li.tf-m");                              // '스포 방지'로 가린 경기 결과: 누르면 보임
    if (sp && document.documentElement.dataset.spoiler === "on" && !sp.classList.contains("lit")) { sp.classList.add("lit"); return; }
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
      m.harvested = true; st.points += add; st.streak += 1; st.best = Math.max(st.best, st.streak); save();
      const li = hb.closest("li"), ground = li.querySelector(".tf-plot");
      hb.outerHTML = `<span class="tf-act tf-pst tf-got">수확 완료 ✓ +${add}</span>`;
      if (ground) sparks(ground, "+" + add);
      setPoints();
      setTimeout(() => growField("n"), 450);
      setTimeout(() => { if (tab === "open") paint(); }, 1400);         // 연출이 끝나면 결과 내역으로 옮김
      return;
    }
    const qb = e.target.closest("[data-quiz-pick]");
    if (qb && board.quiz) {
      const q = board.quiz, pick = +qb.dataset.quizPick;
      if (st.quiz.date === q.date) return;                             // 하루 한 번
      const ok = pick === q.answer;
      st.quiz = { date: q.date, pick, ok };
      if (ok) { st.points += 1; }
      save(); paint();
      if (ok) {
        const b = box.querySelector(`[data-quiz-pick="${pick}"]`); if (b) sparks(b, "+1");
        setPoints(); setTimeout(() => growField("n"), 450);
      }
      return;
    }
    if (e.target.closest("[data-more]")) { more = true; paint(); return; }
    if (e.target.closest(".tf-share")) share();
  });

  // ── 내 기록 공유(복사해서 커뮤니티·메신저에 붙여 넣기) ──
  function shareText() {
    const ms = Object.values(st.plantedMushrooms), t = tier(st.points);
    const won = ms.filter(m => m.status === "won").length, lost = ms.filter(m => m.status === "lost").length;
    const wait = ms.filter(m => m.status === "pending").length;
    return [
      "🍄 티모의 버섯농장 · LCK 독버섯 심기",
      `· ${t.badge} ${t.label} · 농장 점수 ${st.points}점 · 연속 수확 ${st.streak}`,
      `· 맞힌 판 ${won}/${won + lost}${wait ? ` · 결과 기다리는 판 ${wait}` : ""}`,
      `👉 ${location.origin}/lck`,
    ].join("\n");
  }
  function copy(text) {
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
    return new Promise((ok, no) => {                 // 오래된 브라우저·http: 숨은 글상자로 복사
      const ta = document.createElement("textarea");
      ta.value = text; ta.setAttribute("readonly", ""); ta.style.cssText = "position:fixed;top:0;left:0;opacity:0";
      document.body.appendChild(ta); ta.select();
      try { document.execCommand("copy") ? ok() : no(); } catch (err) { no(err); } finally { ta.remove(); }
    });
  }
  // 수확 카드(1:1 그림): 화면 밝기와 상관없이 늘 어두운 게임 카드(차분한 남색 + 에메랄드·골드). 버섯은 농장과 같은 도트 그림
  const PUBLIC_URL = "teemofarm.com/lck";
  function shot() {
    const W = 1080, cv = document.createElement("canvas"); cv.width = W; cv.height = W;
    const c = cv.getContext("2d");
    const fg = "#f8fafc", sub = "#94a3b8", em = "#34d399", am = "#fbbf24", cell = "rgba(15,23,42,.82)", cellLine = "rgba(148,163,184,.22)";
    const font = getComputedStyle(document.body).fontFamily || "sans-serif";
    const F = (w, size) => `${w} ${size}px ${font}`;
    const DARK = { "--shroom": "#e8625a", "--stem": "#e9dcc2" };          // 어두운 화면의 버섯 색(base.css)
    const col = ch => { const k = ART.col[ch] || "#000", m = /^var\((--[\w-]+)\)$/.exec(k); return m ? (DARK[m[1]] || "#e8625a") : k; };
    const sprite = (k, x, y, size) => {
      const g = ART.spr[k] || [], H = g.length, Wd = (g[0] || "").length || 1, cs = size / Wd;
      g.forEach((row, j) => [...row].forEach((ch, i) => { if (ch !== ".") { c.fillStyle = col(ch); c.fillRect(x + i * cs, y + j * cs, Math.ceil(cs), Math.ceil(cs)); } }));
      return H * cs;
    };
    const round = (x, y, w, h, r) => { c.beginPath(); c.moveTo(x + r, y); c.arcTo(x + w, y, x + w, y + h, r); c.arcTo(x + w, y + h, x, y + h, r); c.arcTo(x, y + h, x, y, r); c.arcTo(x, y, x + w, y, r); c.closePath(); };
    const glow = (x, y, r, color) => { const g = c.createRadialGradient(x, y, 0, x, y, r); g.addColorStop(0, color); g.addColorStop(1, "rgba(0,0,0,0)"); c.fillStyle = g; c.fillRect(0, 0, W, W); };
    c.fillStyle = "#0f172a"; c.fillRect(0, 0, W, W);
    round(40, 40, W - 80, W - 80, 48); c.save(); c.clip();
    c.fillStyle = "#131c2e"; c.fillRect(0, 0, W, W);
    glow(W * .85, W * .12, 560, "rgba(16,185,129,.22)");                   // 오른쪽 위 에메랄드
    glow(W * .15, W * .88, 500, "rgba(245,158,11,.14)");                   // 왼쪽 아래 골드
    c.restore();
    round(40, 40, W - 80, W - 80, 48); c.lineWidth = 5; c.strokeStyle = "rgba(52,211,153,.55)"; c.stroke();
    const t = tier(st.points), ms = Object.values(st.plantedMushrooms);
    const won = ms.filter(m => m.status === "won").length, lost = ms.filter(m => m.status === "lost").length;
    c.textBaseline = "alphabetic";
    c.fillStyle = fg; c.font = F(800, 46); c.textAlign = "left"; c.fillText("티모의 버섯농장", 96, 140);
    c.fillStyle = sub; c.font = F(600, 30); c.fillText("LCK 독버섯 심기 · 내 농장 수확 카드", 96, 190);
    c.textAlign = "right"; c.fillText(today().replace(/-/g, "."), W - 96, 140);
    // 가운데: 큰 버섯 + 등급
    c.fillStyle = "rgba(16,185,129,.16)"; c.beginPath(); c.ellipse(W / 2, 480, 190, 40, 0, 0, Math.PI * 2); c.fill();
    sprite(st.points >= 15 ? "gold" : "shroom", W / 2 - 120, 240, 240);
    c.textAlign = "center"; c.fillStyle = em; c.font = F(800, 64); c.fillText(t.label, W / 2, 600);
    // 숫자 네 칸
    const cells = [["농장 점수", st.points + "점"], ["연속 수확 · 최고 " + st.best, String(st.streak)],
                 ["맞힌 판", won + "/" + (won + lost)], ["찾은 황금 버섯", st.goldenFoundDates.length + "개"]];
    const bw = (W - 192 - 3 * 24) / 4;
    cells.forEach(([label, val], i) => {
      const x = 96 + i * (bw + 24);
      round(x, 650, bw, 170, 24); c.fillStyle = cell; c.fill(); c.lineWidth = 2; c.strokeStyle = cellLine; c.stroke();
      c.fillStyle = am; c.font = F(800, 58); c.fillText(val, x + bw / 2, 740);
      c.fillStyle = sub; c.font = F(600, 26); c.fillText(label, x + bw / 2, 790);
    });
    // 내 밭 7칸
    const log = st.fieldLog.slice(-7), ps = 72, gap = 22, x0 = (W - (7 * ps + 6 * gap)) / 2;
    for (let i = 0; i < 7; i++) sprite(log[i] ? (log[i] === "g" ? "gold" : "shroom") : "hole", x0 + i * (ps + gap), 860, ps);
    c.fillStyle = em; c.font = F(800, 34); c.fillText(PUBLIC_URL, W / 2, 1000);
    return cv;
  }
  function share() {
    let d = document.getElementById("tf-shot");
    if (!d) {
      d = document.createElement("dialog"); d.id = "tf-shot"; d.className = "tf-shot"; d.setAttribute("aria-label", "내 농장 수확 카드");
      d.innerHTML = '<img alt="내 농장 수확 카드" width="1080" height="1080"><div class="tf-shot-acts">'
        + '<button type="button" class="tf-o" data-shot="save">이미지 저장</button><button type="button" data-shot="share" hidden>공유하기</button>'
        + '<button type="button" data-shot="copy">글로 복사</button><button type="button" data-shot="close">닫기</button></div>';
      document.body.append(d);
      d.addEventListener("click", e => {
        if (e.target === d) { d.close(); return; }             // 바깥(어두운 곳)을 누르면 닫기
        const b = e.target.closest("[data-shot]"); if (!b) return;
        const say = (t) => { const o = b.textContent; b.textContent = t; setTimeout(() => { b.textContent = o; }, 1500); };
        const k = b.dataset.shot, cv = d._cv;
        if (k === "close") d.close();
        else if (k === "copy") copy(shareText()).then(() => say("복사했어요 ✓")).catch(() => say("복사 못 함"));
        else if (k === "save") { const a = document.createElement("a"); a.href = cv.toDataURL("image/png"); a.download = `teemofarm-${today()}.png`; document.body.append(a); a.click(); a.remove(); }
        else if (k === "share") cv.toBlob(bl => {
          const f = new File([bl], `teemofarm-${today()}.png`, { type: "image/png" });
          navigator.share({ files: [f], text: shareText() }).catch(() => {});
        }, "image/png");
      });
    }
    d._cv = shot();
    d.querySelector("img").src = d._cv.toDataURL("image/png");
    const can = (() => { try { return !!(navigator.canShare && navigator.canShare({ files: [new File([""], "a.png", { type: "image/png" })] })); } catch (e) { return false; } })();
    d.querySelector('[data-shot="share"]').hidden = !can;
    if (typeof d.showModal === "function") d.showModal();
    else copy(shareText()).then(() => toast("내 농장 기록을 복사했어요. 붙여 넣어 자랑해 보세요")).catch(() => {});
  }

  // ── 소식 목록의 '이 소식 O/X 심기 ↑' → 위 독버섯 심기 칸의 그 판으로 ──
  document.addEventListener("click", e => {
    const a = e.target.closest("[data-farm-jump]");
    if (!a) return;
    e.preventDefault();
    const id = a.dataset.farmJump, sel = `li[data-item="${CSS.escape(id)}"]`;
    if (tab !== "open" || !box.querySelector(sel)) { tab = "open"; if (!box.querySelector(sel)) more = true; paint(); }
    const li = box.querySelector(sel) || box;
    li.scrollIntoView({ behavior: "smooth", block: "center" });
    if (li !== box) { li.classList.remove("tf-flash"); void li.offsetWidth; li.classList.add("tf-flash"); }
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
