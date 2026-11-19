// 로스터 짜기: 10팀 × 5포지션. 선수를 고르고 빈칸을 누르거나(모바일) 끌어다 놓기(PC). 이 브라우저에 저장, PNG로 저장·공유
(function () {
  const el = document.getElementById("bdata"); if (!el) return;
  const D = JSON.parse(el.textContent), ROLES = Object.keys(D.pos), KEY = "builder:v1";
  const grid = document.getElementById("bgrid"), pool = document.getElementById("bpool");
  const esc = t => String(t).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const byPage = {}; D.people.forEach(p => { byPage[p.page] = p; });
  const label = p => p.ko || p.nick;

  function current() {   // 지금 로스터(리그피디아 기준)로 채운 판
    const b = {};
    D.teams.forEach(t => { b[t.k] = {}; });
    D.people.filter(p => p.st === "roster" && b[p.team] && ROLES.includes(p.role)).forEach(p => {
      if (!b[p.team][p.role]) b[p.team][p.role] = p.page;
    });
    return b;
  }
  let board;
  try { board = JSON.parse(localStorage.getItem(KEY) || "null"); } catch (e) { board = null; }
  if (!board) board = current();
  // 공유 링크(?r=팀1선수들|팀2선수들…&n=이름)로 들어오면 그 로스터를 보여 줌. '내 버전으로 시작'을 누르기 전엔 내 저장본을 건드리지 않음
  // 짧은 주소(/s/코드)로 들어오면 서버가 넣어 준 D.shared를 씀
  const QS = new URLSearchParams(location.search), SHARED = QS.get("r") || (D.shared && D.shared.r),
        BY = (QS.get("n") || (D.shared && D.shared.n) || "").slice(0, 12);
  let sharedMode = false;
  if (SHARED) {
    sharedMode = true; board = {};
    const parts = SHARED.split("|");
    D.teams.forEach((t, i) => {
      board[t.k] = {};
      (parts[i] || "").split(",").forEach((page, j) => {
        if (!page || !ROLES[j]) return;
        if (!byPage[page]) { const np = { page, nick: page.split(" (")[0], ko: "", real: "", team: "", role: ROLES[j], st: "shared" }; byPage[page] = np; D.people.push(np); }
        board[t.k][ROLES[j]] = page;
      });
    });
  }
  D.teams.forEach(t => { if (!board[t.k]) board[t.k] = {}; });
  const save = () => { if (sharedMode) return; try { localStorage.setItem(KEY, JSON.stringify(board)); } catch (e) {} };
  const bar = document.getElementById("bshared");
  if (SHARED && bar) {
    bar.hidden = false;
    bar.innerHTML = "🍄 <b>" + esc(BY ? BY + "님" : "누군가") + "</b>의 예상 로스터를 보고 있어요. "
      + '<button type="button" class="btn primary" id="bmine">이걸로 내 버전 만들기</button>'
      + '<a class="btn" href="/lck/builder">내 로스터 보기</a>';
    document.getElementById("bmine").onclick = () => {
      sharedMode = false; save(); history.replaceState(null, "", "/lck/builder");
      bar.innerHTML = "내 로스터로 가져왔어요. 고친 뒤 '링크로 공유'로 친구에게 보내 보세요!";
    };
  }
  let sel = null, posF = "all", q = "", freeOnly = false, lock = localStorage.getItem(KEY + ":lock") === "1" && !sharedMode;   // 공유 로스터는 잠금 없이 그대로
  const real = current();   // 리그피디아 기준 확정 선수(잠금 대상)
  const isLocked = (t, r) => lock && !!real[t][r];
  if (lock) D.teams.forEach(t => ROLES.forEach(r => { if (real[t.k][r]) board[t.k][r] = real[t.k][r]; }));
  const lockedPages = () => { const s = new Set(); if (lock) D.teams.forEach(t => ROLES.forEach(r => { if (real[t.k][r]) s.add(real[t.k][r]); })); return s; };

  function used() { const u = new Set(); Object.values(board).forEach(r => Object.values(r).forEach(p => p && u.add(p))); return u; }
  function drawPool() {
    const u = used();
    const list = D.people.filter(p => ROLES.includes(p.role) && (posF === "all" || p.role === posF)
      && (!freeOnly || !p.team) && (!q || [p.nick, p.ko, p.real].some(x => x && x.toLowerCase().includes(q))));
    list.sort((a, b) => ROLES.indexOf(a.role) - ROLES.indexOf(b.role) || label(a).localeCompare(label(b), "ko"));
    pool.innerHTML = list.map(p => '<li><span class="pchip' + (sel === p.page ? " sel" : "") + (u.has(p.page) ? " used" : "")
      + '" draggable="true" data-page="' + esc(p.page) + '">' + esc(label(p)) + "<small>" + D.pos[p.role] + "</small></span></li>").join("")
      || '<li class="src">조건에 맞는 선수가 없어요</li>';
  }
  function drawGrid() {
    grid.innerHTML = D.teams.map(t => '<section class="bteam" style="--tc:' + t.color + '"><header>'
      + (t.logo ? '<img class="logo" src="' + esc(t.logo) + '" alt="" width="20" height="20">' : "") + esc(t.short) + "</header><ol>"
      + ROLES.map(r => { const p = byPage[board[t.k][r]];
        const lk = isLocked(t.k, r);
        return '<li class="bslot' + (p ? "" : " empty") + (lk ? " locked" : sel ? " target" : "") + '" data-t="' + t.k + '" data-r="' + r + '"><small>' + D.pos[r] + "</small><b>"
          + (p ? esc(label(p)) : '<span class="plus" aria-label="비어 있음">+</span>') + "</b>" + (p && !lk ? '<button type="button" class="rm" aria-label="빼기">×</button>' : "") + "</li>"; }).join("")
      + "</ol></section>").join("");
  }
  const draw = () => { drawPool(); drawGrid(); };
  function place(page, t, r) {
    if (isLocked(t, r) || lockedPages().has(page)) return;   // 잠긴 자리·잠긴 선수는 못 옮김
    Object.keys(board).forEach(k => Object.keys(board[k]).forEach(x => { if (board[k][x] === page) delete board[k][x]; }));   // 한 선수는 한 자리만
    board[t][r] = page; sel = null; save(); draw();
  }

  pool.addEventListener("click", e => { const c = e.target.closest(".pchip"); if (!c || lockedPages().has(c.dataset.page)) return; sel = sel === c.dataset.page ? null : c.dataset.page; draw(); });
  grid.addEventListener("click", e => {
    const s = e.target.closest(".bslot"); if (!s || s.classList.contains("locked")) return;
    if (e.target.closest(".rm")) { delete board[s.dataset.t][s.dataset.r]; save(); draw(); return; }
    if (sel) place(sel, s.dataset.t, s.dataset.r);
    else if (board[s.dataset.t][s.dataset.r]) { sel = board[s.dataset.t][s.dataset.r]; draw(); }   // 칸의 선수를 골라 다른 칸으로 옮기기
  });
  document.addEventListener("dragstart", e => { const c = e.target.closest(".pchip"); if (c) e.dataTransfer.setData("text/plain", c.dataset.page); });
  grid.addEventListener("dragover", e => { const s = e.target.closest(".bslot"); if (s) { e.preventDefault(); s.classList.add("over"); } });
  grid.addEventListener("dragleave", e => { const s = e.target.closest(".bslot"); if (s) s.classList.remove("over"); });
  grid.addEventListener("drop", e => { const s = e.target.closest(".bslot"); if (!s) return; e.preventDefault(); const pg = e.dataTransfer.getData("text/plain"); if (byPage[pg]) place(pg, s.dataset.t, s.dataset.r); });
  document.getElementById("bq").addEventListener("input", e => { q = e.target.value.trim().toLowerCase(); drawPool(); });
  const lk = document.getElementById("block"); lk.checked = lock;
  lk.addEventListener("change", () => {
    lock = lk.checked; try { localStorage.setItem(KEY + ":lock", lock ? "1" : ""); } catch (e) {}
    if (lock) D.teams.forEach(t => ROLES.forEach(r => { if (real[t.k][r]) {   // 확정 선수를 제자리로
      Object.keys(board).forEach(k => Object.keys(board[k]).forEach(x => { if (board[k][x] === real[t.k][r]) delete board[k][x]; }));
      board[t.k][r] = real[t.k][r]; } }));
    sel = null; save(); draw();
  });
  document.getElementById("bfree").addEventListener("change", e => { freeOnly = e.target.checked; drawPool(); });
  document.getElementById("bpos").addEventListener("click", e => {
    const b = e.target.closest("button[data-p]"); if (!b) return;
    posF = b.dataset.p; document.querySelectorAll("#bpos button").forEach(x => x.classList.toggle("on", x === b)); drawPool();
  });
  document.getElementById("breset").onclick = () => { board = current(); sel = null; save(); draw(); };
  document.getElementById("bclear").onclick = () => {   // 잠금이 켜져 있으면 확정 선수는 남김
    D.teams.forEach(t => { board[t.k] = {}; if (lock) ROLES.forEach(r => { if (real[t.k][r]) board[t.k][r] = real[t.k][r]; }); });
    sel = null; save(); draw();
  };

  // ── 지난 시즌 로스터 불러오기(아카이브) ──
  async function loadArchive(y, btn) {
    const old = btn ? btn.textContent : "";
    if (btn) btn.textContent = "불러오는 중…";
    try {
      const r = await (await fetch("/api/archive?year=" + y)).json();
      if (!r.ready || !r.roster.length) { if (btn) btn.textContent = y + " 기록 모으는 중 · 잠시 뒤 다시"; setTimeout(() => { if (btn) btn.textContent = old; }, 4000); return; }
      lock = false; lk.checked = false; try { localStorage.setItem(KEY + ":lock", ""); } catch (e) {}
      D.teams.forEach(t => { board[t.k] = {}; });
      r.roster.forEach(p => {
        if (!p.team || !board[p.team] || !ROLES.includes(p.role) || board[p.team][p.role]) return;
        if (!byPage[p.page]) { const np = { page: p.page, nick: p.nick, ko: "", real: "", team: p.team, role: p.role, st: "archive" }; byPage[p.page] = np; D.people.push(np); }
        board[p.team][p.role] = p.page;
      });
      sel = null; save(); draw();
      if (btn) { btn.textContent = y + " 로스터 불러옴"; setTimeout(() => { btn.textContent = old; }, 2500); }
    } catch (e) { if (btn) btn.textContent = old; }
  }
  document.querySelectorAll("button[data-arch]").forEach(b => b.addEventListener("click", () => loadArchive(b.dataset.arch, b)));
  const qy = new URLSearchParams(location.search).get("season");
  if (qy && document.querySelector('button[data-arch="' + qy + '"]')) loadArchive(qy, document.querySelector('button[data-arch="' + qy + '"]'));

  // ── 이미지 카드(PNG) ──
  async function png() {
    const W = 1080, PAD = 40, CW = (W - PAD * 3) / 2, CH = 150, rows = Math.ceil(D.teams.length / 2), H = 170 + rows * (CH + 20) + 70;
    const c = document.createElement("canvas"); c.width = W; c.height = H; const g = c.getContext("2d");
    const font = (w, s) => w + " " + s + "px 'Pretendard GOV Variable','Pretendard GOV','Apple SD Gothic Neo','Malgun Gothic',sans-serif";
    g.fillStyle = "#0f1419"; g.fillRect(0, 0, W, H);
    g.fillStyle = "#7cff01"; g.font = font(800, 44); g.fillText("🍄 내가 단장이라면: " + (D.year || "") + " LCK", PAD, 80);
    g.fillStyle = "#94a3b8"; g.font = font(500, 22); g.fillText("티모의 버섯농장 · 단장 놀이", PAD, 120);
    const logos = {};
    await Promise.all(D.teams.filter(t => t.logo).map(t => new Promise(res => { const i = new Image(); i.onload = () => { logos[t.k] = i; res(); }; i.onerror = res; i.src = t.logo; })));
    D.teams.forEach((t, i) => {
      const x = PAD + (i % 2) * (CW + PAD), y = 160 + Math.floor(i / 2) * (CH + 20);
      g.fillStyle = "#192028"; g.beginPath(); g.roundRect ? g.roundRect(x, y, CW, CH, 14) : g.rect(x, y, CW, CH); g.fill();
      g.fillStyle = t.color || "#9d65d6"; g.fillRect(x, y, CW, 6);
      if (logos[t.k]) { g.fillStyle = "#fff"; g.beginPath(); g.arc(x + 36, y + 42, 18, 0, 7); g.fill(); g.drawImage(logos[t.k], x + 22, y + 28, 28, 28); }
      g.fillStyle = "#f1f5f9"; g.font = font(800, 26); g.fillText(t.short, x + 64, y + 52);
      const sw = (CW - 20) / 5;
      ROLES.forEach((r, j) => {
        const p = byPage[board[t.k][r]], sx = x + 10 + j * sw;
        g.fillStyle = "#7b8798"; g.font = font(600, 17); g.fillText(D.pos[r], sx + 6, y + 92);
        g.fillStyle = p ? "#f1f5f9" : "#4b5563";
        // 긴 이름(구마유시·딜라이트·쇼메이커 등)은 자르지 않고 글씨를 줄여서 다 보이게. 그래도 넘치면 그때만 자름
        let n = p ? label(p) : "—", size = 21;
        g.font = font(700, size);
        while (g.measureText(n).width > sw - 10 && size > 13) { size--; g.font = font(700, size); }
        while (g.measureText(n).width > sw - 10 && n.length > 1) n = n.slice(0, -1);
        g.fillText(n, sx + 6, y + 124);
      });
    });
    // 아래 워터마크: 사이트 이름 + 주소(무슨 사이트인지 한눈에)
    const mark = "🍄 티모의 버섯농장 · 단장 놀이 · " + (D.year || "") + " LCK";
    g.fillStyle = "#c39cf0"; g.font = font(700, 20); g.fillText(mark, PAD, H - 30);
    const mw = g.measureText(mark).width;
    g.fillStyle = "#7b8798"; g.font = font(500, 18); g.fillText(D.domain || (location.host + "/lck/builder"), PAD + mw + 16, H - 30);   // 사이트 주소(site.json의 domain)
    return new Promise(res => c.toBlob(res, "image/png"));
  }
  document.getElementById("bsave").onclick = async () => {
    const b = await png(); const a = document.createElement("a");
    a.href = URL.createObjectURL(b); a.download = "버섯농장_로스터.png"; document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 4000);
  };
  // 링크로 공유: 지금 판을 주소에 담아서 보냄(받은 사람이 그대로 열고 고쳐서 다시 공유)
  document.getElementById("bshare").onclick = async () => {
    const btn = document.getElementById("bshare");
    const enc = D.teams.map(t => ROLES.map(r => board[t.k][r] || "").join(",")).join("|");
    let name = ""; try { name = localStorage.getItem("chatName") || ""; } catch (e) {}
    let url = location.origin + "/lck/builder?r=" + encodeURIComponent(enc) + (name ? "&n=" + encodeURIComponent(name) : "");
    try {   // 짧은 주소 받기(실패하면 긴 주소 그대로)
      const res = await fetch("/api/share", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ r: enc, n: name }) });
      if (res.ok) { const j = await res.json(); if (j.code) url = location.origin + "/s/" + j.code; }
    } catch (e) {}
    const text = "내 2027 LCK 예상 로스터 어때? 너도 짜 봐 🍄";
    if (navigator.share && matchMedia("(pointer: coarse)").matches) {
      try { await navigator.share({ title: "나만의 LCK 예상 로스터 · 티모의 버섯농장", text, url }); return; } catch (e) { if (e && e.name === "AbortError") return; }
    }
    try { await navigator.clipboard.writeText(url); btn.textContent = "링크 복사됨"; }
    catch (e) { prompt("이 주소를 복사해서 보내세요", url); }
    setTimeout(() => { btn.textContent = "링크로 공유"; }, 2500);
  };
  draw();
})();
