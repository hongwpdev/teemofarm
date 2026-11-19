// 공통: [조회]·자동 조회, 내 팀 기억, 메뉴 사이 필터 기억, 팀 탭(가운데로 스크롤·더 있음 표시)
(function () {
  const B = document.body.dataset;
  const LG = B.league || "lck", SEC = B.sec || "", SCOPE = B.scope || "";
  const AUTO_MS = (+B.auto || 5) * 60 * 1000;
  const store = {
    get(k) { try { return localStorage.getItem(k) || ""; } catch (e) { return ""; } },
    set(k, v) { try { v ? localStorage.setItem(k, v) : localStorage.removeItem(k); } catch (e) {} },
  };
  window.SPS = { store, MY: "myTeam:" + LG };

  // ── 화면 밝기(협곡의 밤/낮) · 스포 방지(실명 다트) ──
  const root = document.documentElement, thm = document.getElementById("thm"), spo = document.getElementById("spo");
  // 테마 버튼: 선 아이콘(달/해) — 서버가 처음엔 달을 그리고, 여기서 지금 테마에 맞춰 바꿈
  const SVG = '<svg class="i" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">';
  const MOON = SVG + '<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/></svg>';
  const SUN = SVG + '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>';
  const syncTheme = () => { if (thm) { const d = root.dataset.theme !== "light"; thm.innerHTML = d ? MOON : SUN; thm.setAttribute("aria-label", d ? "밝은 화면으로" : "어두운 화면으로"); } };
  if (thm) thm.addEventListener("click", () => { root.dataset.theme = root.dataset.theme === "light" ? "dark" : "light"; store.set("theme", root.dataset.theme); syncTheme(); });
  syncTheme();
  const syncSpo = () => { if (spo) spo.setAttribute("aria-pressed", root.dataset.spoiler === "on" ? "true" : "false"); };
  if (spo) spo.addEventListener("click", () => {
    const on = root.dataset.spoiler !== "on";
    if (on) root.dataset.spoiler = "on"; else delete root.dataset.spoiler;
    store.set("spoiler", on ? "1" : ""); syncSpo();
  });
  syncSpo();

  // ── 리그 고르기: 바깥을 누르거나 ESC면 닫힘 ──
  const lgsel = document.querySelector(".lgsel");
  if (lgsel) {
    document.addEventListener("click", e => { if (lgsel.open && !lgsel.contains(e.target)) lgsel.open = false; });
    document.addEventListener("keydown", e => { if (e.key === "Escape" && lgsel.open) lgsel.open = false; });
  }

  // ── 후원 버튼: 송금 링크는 휴대폰 전용이라, PC(마우스)에서는 QR을 띄움 ──
  const sup = document.querySelector(".support a[data-qr]");
  if (sup) {
    const box = sup.parentNode.querySelector(".sup-qr");
    sup.addEventListener("click", e => {
      if (!matchMedia("(hover: hover) and (pointer: fine)").matches) return;   // 휴대폰은 링크로
      e.preventDefault(); box.hidden = !box.hidden;
    });
    box.querySelector("button").onclick = () => { box.hidden = true; };
  }

  // ── 맨 위로(긴 목록에서) ──
  const top = document.createElement("button");
  top.type = "button"; top.className = "totop"; top.textContent = "↑ 위로"; top.setAttribute("aria-label", "맨 위로");
  top.onclick = () => { top.blur(); window.scrollTo({ top: 0, behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" }); };
  document.body.append(top);
  const onScroll = () => top.classList.toggle("show", window.scrollY > 700 && !root.classList.contains("chat-open"));
  window.addEventListener("scroll", onScroll, { passive: true }); onScroll();

  // ── 이스터에그: 제목 옆 버섯을 2초 안에 5번 누르면 포자가 쏟아짐 ──
  const teemo = document.getElementById("teemo");
  if (teemo) {
    let taps = [];
    teemo.addEventListener("click", () => {
      const now = Date.now(); taps = taps.filter(t => now - t < 2000); taps.push(now);
      if (taps.length < 5) return;
      taps = [];
      for (let i = 0; i < 36; i++) {
        const e = document.createElement("span");
        e.className = "rain"; e.textContent = i % 4 ? "🍄" : "✨";
        e.style.left = Math.random() * 100 + "vw"; e.style.animationDuration = (1.6 + Math.random() * 1.8) + "s";
        e.style.animationDelay = Math.random() * .6 + "s"; e.style.fontSize = (1.6 + Math.random() * 1.8) + "rem";
        document.body.append(e); setTimeout(() => e.remove(), 4200);
      }
    });
  }

  // ── 내 팀: 주소에 팀이 없으면 내 팀으로 열기(소식 화면) ──
  const qs = new URLSearchParams(location.search);
  const my = store.get(window.SPS.MY);
  if (B.teamable && my && !qs.has("team") && !qs.has("q")) {
    qs.set("team", my);
    location.replace(location.pathname + "?" + qs.toString());
    return;
  }

  // ── [조회]·자동 조회 ──
  const go = document.getElementById("go"), auto = document.getElementById("auto"),
        msg = document.getElementById("msg"), next = document.getElementById("next");
  if (go && auto) {
    let timer = null, tick = null;
    const say = t => { if (msg) msg.textContent = t; };
    const FA_ONLY = SCOPE.indexOf("fa") >= 0;
    const STEPS = FA_ONLY ? [["fa", "FA·로스터"]] : [["wiki", "위키"], ["news", "뉴스"], ["fa", "FA·로스터"]];
    let ld = null;
    // '조회 중' 화면: 반투명 덮개 + 달리는 버섯 + 끝난 단계 표시. [가리기]를 누르면 뒤에서 계속 모음
    // 조회 중 화면: 숲길을 따라 티모(라이엇 공식 챔피언 아이콘)가 돌아다니며 버섯(공식 아이콘)을 심음
    // 길·부쉬는 사이트가 직접 그린 단순한 배경이고, 캐릭터·버섯은 라이엇 공식 이미지를 씀(Riot 팬 콘텐츠 정책)
    const TEEMO_IMG = "https://ddragon.leagueoflegends.com/cdn/16.23.1/img/champion/Teemo.png";
    let farm = null;
    function farmLoop(canvas) {
      const W = 240, H = 84, ctx = canvas.getContext("2d"), dpr = Math.min(window.devicePixelRatio || 1, 3);
      canvas.width = W * dpr; canvas.height = H * dpr; ctx.scale(dpr, dpr);
      const path = [{ x: 24, y: 58 }, { x: 74, y: 34 }, { x: 132, y: 56 }, { x: 188, y: 30 }, { x: 214, y: 54 }, { x: 158, y: 66 }, { x: 96, y: 62 }, { x: 42, y: 66 }];
      const plantAt = [1, 2, 3, 5, 6], bushes = [[46, 22], [128, 20], [196, 64], [8, 30]];
      const shroom = new Image(), teemo = new Image();
      shroom.src = "/img/shroom.png"; teemo.src = TEEMO_IMG;
      let seg = 0, t = 0, tick = 0, id = 0, mush = [];
      const ok = im => im.complete && im.naturalWidth > 0;
      const css = getComputedStyle(document.documentElement);
      const pathColor = (css.getPropertyValue("--primary") || "#8b5cf6").trim();
      function drawMap() {
        ctx.save(); ctx.globalAlpha = .35; ctx.strokeStyle = pathColor; ctx.lineWidth = 2; ctx.setLineDash([4, 4]);
        ctx.beginPath(); path.forEach((p, i) => i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y)); ctx.closePath(); ctx.stroke(); ctx.restore();
        bushes.forEach(([x, y]) => {           // 부쉬: 둥근 풀 덩어리 세 개
          ctx.fillStyle = "#1f4d3a";
          [[0, 4, 7], [8, 2, 8], [16, 5, 6]].forEach(([dx, dy, r]) => { ctx.beginPath(); ctx.arc(x + dx, y + dy, r, 0, Math.PI * 2); ctx.fill(); });
          ctx.fillStyle = "rgba(74,222,128,.25)"; ctx.beginPath(); ctx.arc(x + 8, y, 4, 0, Math.PI * 2); ctx.fill();
        });
      }
      function drawShroom(m) {
        const grow = m.life < 12 ? .5 + m.life / 24 : 1;
        const a = m.life > m.max - 60 ? Math.max(.22, (m.max - m.life) / 60) : 1;   // 서서히 투명해짐(은신)
        const s = 20 * grow;
        ctx.save(); ctx.globalAlpha = a;
        ctx.fillStyle = "rgba(74,222,128,.18)"; ctx.beginPath(); ctx.ellipse(m.x, m.y + 2, s * .7, s * .3, 0, 0, Math.PI * 2); ctx.fill();
        if (ok(shroom)) {                       // 공식 아이콘(네모)을 동그랗게 잘라서
          const cx = m.x, cy = m.y - s / 2 + 3;
          ctx.save(); ctx.beginPath(); ctx.arc(cx, cy, s / 2, 0, Math.PI * 2); ctx.clip();
          ctx.drawImage(shroom, cx - s / 2, cy - s / 2, s, s); ctx.restore();
          ctx.strokeStyle = "rgba(163,230,53,.7)"; ctx.lineWidth = 1; ctx.beginPath(); ctx.arc(cx, cy, s / 2, 0, Math.PI * 2); ctx.stroke();
        }
        else { ctx.font = s + "px sans-serif"; ctx.textAlign = "center"; ctx.fillText("🍄", m.x, m.y + 2); }
        ctx.restore();
      }
      function drawTeemo(x, y, hop) {
        const r = 14, cy = y - r - 2 - hop;
        ctx.fillStyle = "rgba(0,0,0,.4)"; ctx.beginPath(); ctx.ellipse(x, y + 1, 8 - hop * .6, 2.5, 0, 0, Math.PI * 2); ctx.fill();
        ctx.save(); ctx.beginPath(); ctx.arc(x, cy, r, 0, Math.PI * 2); ctx.closePath();
        if (ok(teemo)) { ctx.clip(); ctx.drawImage(teemo, x - r, cy - r, r * 2, r * 2); }
        else { ctx.fillStyle = pathColor; ctx.fill(); }
        ctx.restore();
        ctx.strokeStyle = "#a3e635"; ctx.lineWidth = 1.5; ctx.beginPath(); ctx.arc(x, cy, r, 0, Math.PI * 2); ctx.stroke();
      }
      function frame() {
        tick++; ctx.clearRect(0, 0, W, H); drawMap();
        let p1 = path[seg], p2 = path[(seg + 1) % path.length];
        t += 1.15 / Math.hypot(p2.x - p1.x, p2.y - p1.y);
        if (t >= 1) {             // 다음 지점 도착: 구간을 바꾼 뒤 위치를 새 구간에서 계산(예전엔 한 프레임 지난 구간 시작점으로 튀어서 깜빡였음)
          t = 0; seg = (seg + 1) % path.length;
          if (plantAt.includes(seg)) { mush = mush.filter(m => Math.hypot(m.x - p2.x, m.y - p2.y) > 8); mush.push({ x: p2.x, y: p2.y, life: 0, max: 260 }); }
          p1 = path[seg]; p2 = path[(seg + 1) % path.length];
        }
        mush.forEach(m => { m.life++; drawShroom(m); }); mush = mush.filter(m => m.life < m.max);
        const planting = t < .12 && plantAt.includes(seg);
        drawTeemo(p1.x + (p2.x - p1.x) * t, p1.y + (p2.y - p1.y) * t, planting ? 0 : Math.abs(Math.sin(tick / 5)) * 3);
        id = requestAnimationFrame(frame);
      }
      const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
      if (still) { drawMap(); plantAt.forEach(i => drawShroom({ x: path[i].x, y: path[i].y, life: 99, max: 999 })); drawTeemo(path[0].x, path[0].y, 0); return { stop() {} }; }
      id = requestAnimationFrame(frame);
      return { stop() { cancelAnimationFrame(id); } };
    }
    function overlay(on) {
      if (!on) { if (ld) ld.hidden = true; if (farm) { farm.stop(); farm = null; } return; }
      if (!ld) {
        ld = document.createElement("div");
        ld.className = "loading"; ld.setAttribute("role", "status"); ld.setAttribute("aria-live", "polite");
        ld.innerHTML = '<div class="ld"><div class="track farm"><canvas aria-hidden="true"></canvas></div>' +
          '<b class="ld-t">협곡에 버섯 심는 중…</b><p>' + (FA_ONLY ? "FA·로스터를" : "새 소식·로스터·FA를") + ' 모으고 있어요</p>' +
          '<div class="steps"></div><button class="hide" type="button">가리기 (뒤에서 계속 모아요)</button></div>';
        ld.querySelector(".hide").addEventListener("click", () => { ld.hidden = true; if (farm) { farm.stop(); farm = null; } });
        document.body.append(ld);
      }
      steps([]); ld.hidden = false;
      if (!farm) farm = farmLoop(ld.querySelector(".farm canvas"));
    }
    function steps(done) {
      if (!ld) return;
      let now = false;
      ld.querySelector(".steps").innerHTML = STEPS.map(([k, label]) => {
        if (done.indexOf(k) >= 0) return '<span class="done">' + label + ' ✓</span>';
        if (!now) { now = true; return '<span class="now">' + label + '</span>'; }
        return "<span>" + label + "</span>";
      }).join("");
    }
    const busy = on => { go.disabled = on; go.classList.toggle("busy", on); go.querySelector(".lbl").textContent = on ? "조회 중…" : "조회"; if (on && next) next.textContent = ""; overlay(on); };
    async function waitDone() {
      for (let i = 0; i < 90; i++) {            // 최대 3분 기다림
        await new Promise(r => setTimeout(r, 2000));
        try {
          const st = await (await fetch("/api/status" + SCOPE)).json();
          steps(st.done || []);
          if (!st.running) return true;
        } catch (e) {}
      }
      return false;
    }
    async function collect() {
      clearTimeout(timer); clearInterval(tick); if (next) next.textContent = "";
      busy(true); say("");
      try {
        const res = await (await fetch("/api/refresh" + SCOPE, { method: "POST" })).json();
        if (res.status === "cooldown") {
          overlay(false);
          say("방금 수집했어요. 최신 목록을 보여드려요 (" + res.wait + "초 뒤 다시 가능)");
          setTimeout(() => location.reload(), 1500);
          return;
        }
        await waitDone();
        if (ld && !ld.hidden) { const t = ld.querySelector(".ld-t"); t.textContent = "시야 확보 완료!"; t.classList.add("done-msg"); await new Promise(r => setTimeout(r, 500)); }
        location.reload();
      } catch (e) { say("조회 실패: 서버에 연결할 수 없어요"); busy(false); }
    }
    const left = ms => { const s = Math.max(0, Math.ceil(ms / 1000)); return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0"); };
    function schedule() {
      clearTimeout(timer); clearInterval(tick); if (next) next.textContent = ""; go.title = "지금 새로 가져오기";
      if (!auto.checked) return;
      const due = Date.now() + AUTO_MS;
      timer = setTimeout(collect, AUTO_MS);
      const show = () => { if (next) next.textContent = left(due - Date.now()); go.title = "지금 새로 가져오기 · 다음 자동 조회 " + left(due - Date.now()) + " 뒤"; };
      show(); tick = setInterval(show, 1000);
    }
    go.addEventListener("click", collect);
    auto.addEventListener("change", () => {
      store.set("lckAuto", auto.checked ? "1" : "");
      say(auto.checked ? "자동 조회 켜짐: " + (+B.auto || 5) + "분마다 새로 가져와요" : "자동 조회 꺼짐");
      schedule();
    });
    auto.checked = store.get("lckAuto") === "1";
    schedule();
  }

  // ── 메뉴(소식·로스터·이적·일정)를 오가도 고른 필터가 남도록(이 브라우저 탭에서만) ──
  try {
    const key = "qs:" + LG + ":" + SEC;
    const keep = () => sessionStorage.setItem(key, location.search);
    keep(); window.addEventListener("pagehide", keep);
    document.querySelectorAll("a[data-sec]").forEach(a => {
      a.addEventListener("click", keep);
      const saved = sessionStorage.getItem("qs:" + LG + ":" + a.dataset.sec);
      if (saved && a.dataset.sec !== SEC) a.href = a.getAttribute("href").split("?")[0] + saved;
    });
  } catch (e) {}

  // ── 팀 탭: 고른 탭을 가운데로, 옆에 더 있으면 오른쪽 끝 흐리게, 내 팀에 별 ──
  const tabs = document.getElementById("tabs");
  if (tabs) {
    const wrap = tabs.closest(".tabs-wrap");
    const hint = () => { if (wrap) wrap.classList.toggle("more", tabs.scrollLeft + tabs.clientWidth < tabs.scrollWidth - 4); };
    const center = () => { const on = tabs.querySelector("a.on"); if (on) tabs.scrollLeft = on.offsetLeft - (tabs.clientWidth - on.offsetWidth) / 2; hint(); };
    tabs.addEventListener("scroll", hint, { passive: true });
    window.addEventListener("resize", hint);
    window.SPS.centerTabs = center;
    window.SPS.markMy = () => {
      tabs.querySelectorAll(".star").forEach(s => s.remove());
      const m = store.get(window.SPS.MY);
      const a = m && tabs.querySelector('a[data-t="' + m + '"] span');
      if (a) a.insertAdjacentHTML("afterend", '<span class="star" aria-label="내 팀">★</span>');
    };
    window.SPS.markMy();
    center();
  }
})();

// 사이트 소개·개인정보처리방침: 아래쪽 링크를 누르면 팝업으로(지원 안 되는 브라우저는 /about·/privacy 페이지로 이동)
(() => {
  document.addEventListener("click", e => {
    const a = e.target.closest && e.target.closest("a[data-pol]");
    if (!a) return;
    const d = document.getElementById("pol-" + a.dataset.pol);
    if (!d || typeof d.showModal !== "function") return;
    e.preventDefault();
    d.showModal();
    d.scrollTop = 0;
  });
  // 바깥(어두운 부분)을 누르면 닫기
  document.querySelectorAll(".pol-dlg").forEach(d => d.addEventListener("click", e => {
    if (e.target !== d) return;
    const r = d.getBoundingClientRect();
    if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) d.close();
  }));
})();
