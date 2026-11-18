// 미니게임: 협곡 버섯 탐지(지뢰찾기). 첫 칸은 항상 안전, 오른쪽 클릭·길게 누르기·렌즈 모드로 🔴 표시
(function () {
  const boardEl = document.getElementById("gboard"); if (!boardEl) return;
  const $ = id => document.getElementById(id);
  let R, C, N, cells, started, over, flags, t0, tick, mode = "dig";

  function init() {
    [R, C, N] = $("glv").value.split(",").map(Number);
    cells = Array.from({ length: R * C }, () => ({ m: false, open: false, flag: false, n: 0 }));
    started = over = false; flags = 0; $("gshare").hidden = true; $("gshare").textContent = "🍄 기록 자랑하기"; clearInterval(tick); $("gtime").textContent = "0초";
    $("gleft").textContent = N; say("부쉬를 탐지하세요!");
    boardEl.style.gridTemplateColumns = "repeat(" + C + ",1fr)";
    boardEl.innerHTML = cells.map((_, i) => '<div class="gcell" data-i="' + i + '" role="button" aria-label="칸"></div>').join("");
    best();
  }
  const say = (t, c) => { $("gmsg").textContent = t; $("gmsg").style.color = c || ""; };
  const near = i => { const r = Math.floor(i / C), c = i % C, out = [];
    for (let dr = -1; dr <= 1; dr++) for (let dc = -1; dc <= 1; dc++) { const nr = r + dr, nc = c + dc;
      if ((dr || dc) && nr >= 0 && nr < R && nc >= 0 && nc < C) out.push(nr * C + nc); } return out; };
  function plant(safe) {   // 첫 칸과 그 주변엔 버섯을 두지 않음
    const ban = new Set([safe, ...near(safe)]); let k = 0;
    while (k < N) { const i = Math.floor(Math.random() * R * C); if (!cells[i].m && !ban.has(i)) { cells[i].m = true; k++; } }
    cells.forEach((c, i) => { c.n = near(i).filter(j => cells[j].m).length; });
    started = true; t0 = Date.now(); tick = setInterval(() => { $("gtime").textContent = Math.floor((Date.now() - t0) / 1000) + "초"; }, 500);
  }
  function paint(i) {
    const c = cells[i], e = boardEl.children[i];
    e.className = "gcell" + (c.open ? " open" : "") + (c.open && c.m ? " boom" : "") + (c.open && !c.m && c.n ? " n" + c.n : "");
    e.textContent = c.open ? (c.m ? "🍄" : c.n || "") : c.flag ? "🔴" : "";
  }
  function open(i) {
    const st = [i];
    while (st.length) { const j = st.pop(), c = cells[j]; if (c.open || c.flag) continue; c.open = true; paint(j);
      if (!c.m && c.n === 0) near(j).forEach(k => { if (!cells[k].open) st.push(k); }); }
  }
  function dig(i) {
    if (over || cells[i].open || cells[i].flag) return;
    if (!started) plant(i);
    if (cells[i].m) {
      over = true; clearInterval(tick);
      cells.forEach((c, j) => { if (c.m) { c.open = true; paint(j); } });
      say("💥 유독성 함정 발동!", "#c084fc"); return;
    }
    open(i);
    if (cells.filter(c => !c.m && c.open).length === R * C - N) {
      over = true; clearInterval(tick);
      const s = Math.floor((Date.now() - t0) / 1000); say("🎉 협곡 시야 장악 완료! " + s + "초", "var(--lime)");
      const k = "mine:" + $("glv").value, b = +localStorage.getItem(k) || 0;
      if (!b || s < b) { try { localStorage.setItem(k, String(s)); } catch (e) {} }
      best();
      const lv = $("glv").selectedOptions[0].textContent, sh = $("gshare");
      sh.hidden = false;
      sh.onclick = async () => {
        const text = "🍄 티모의 버섯농장 버섯 탐지(" + lv + ") " + s + "초 클리어!" + (!b || s < b ? " (최고 기록)" : "") + " " + location.origin + "/lck/game";
        try { if (navigator.share) { await navigator.share({ text }); return; } } catch (e) { return; }
        try { await navigator.clipboard.writeText(text); sh.textContent = "복사했어요! 붙여넣어 자랑하세요"; } catch (e) { sh.textContent = text; }
      };
    }
  }
  function flag(i) {
    if (over || cells[i].open) return;
    cells[i].flag = !cells[i].flag; flags += cells[i].flag ? 1 : -1; paint(i);
    $("gleft").textContent = Math.max(0, N - flags);
  }
  function best() { const b = +localStorage.getItem("mine:" + $("glv").value) || 0; $("gbest").textContent = b ? "· 최고 기록 " + b + "초" : ""; }

  let press = null, longDone = false;
  boardEl.addEventListener("pointerdown", e => {
    const c = e.target.closest(".gcell"); if (!c) return; longDone = false;
    if (e.pointerType !== "mouse") press = setTimeout(() => { longDone = true; flag(+c.dataset.i); if (navigator.vibrate) navigator.vibrate(30); }, 420);
  });
  ["pointerup", "pointerleave", "pointercancel"].forEach(t => boardEl.addEventListener(t, () => clearTimeout(press)));
  boardEl.addEventListener("click", e => {
    const c = e.target.closest(".gcell"); if (!c || longDone) return;
    mode === "flag" ? flag(+c.dataset.i) : dig(+c.dataset.i);
  });
  boardEl.addEventListener("contextmenu", e => { const c = e.target.closest(".gcell"); if (c) { e.preventDefault(); flag(+c.dataset.i); } });
  document.querySelector(".gmode").addEventListener("click", e => {
    const b = e.target.closest("button[data-m]"); if (!b) return; mode = b.dataset.m;
    document.querySelectorAll(".gmode button").forEach(x => x.classList.toggle("on", x === b));
  });
  $("gnew").onclick = init; $("glv").onchange = init;
  init();
})();
