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
  const syncTheme = () => { if (thm) { const d = root.dataset.theme !== "light"; thm.textContent = d ? "🌙" : "☀️"; thm.setAttribute("aria-label", d ? "밝은 화면으로" : "어두운 화면으로"); } };
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
  top.type = "button"; top.className = "totop"; top.textContent = "🍄 위로"; top.setAttribute("aria-label", "맨 위로");
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
    function overlay(on) {
      if (!on) { if (ld) ld.hidden = true; return; }
      if (!ld) {
        ld = document.createElement("div");
        ld.className = "loading"; ld.setAttribute("role", "status"); ld.setAttribute("aria-live", "polite");
        const sprout = c => '<svg class="sprout ' + c + '" viewBox="0 0 40 40" aria-hidden="true"><rect x="15" y="20" width="10" height="20" rx="4" fill="#f4ead6"/><path d="M3 24 C3 10 12 4 20 4 C28 4 37 10 37 24Z" fill="#c9a36a"/></svg>';
        ld.innerHTML = '<div class="ld"><div class="track">' + sprout("a") + sprout("b") + sprout("c") +
          '<i class="dust"></i><i class="dust b"></i><div class="runner"></div></div>' +
          '<b class="ld-t">협곡에 버섯 심는 중…</b><p>' + (FA_ONLY ? "FA·로스터를" : "새 소식·로스터·FA를") + ' 모으고 있어요</p>' +
          '<div class="steps"></div><button class="hide" type="button">가리기 (뒤에서 계속 모아요)</button></div>';
        const runner = ld.querySelector(".runner"), img = new Image();
        img.className = "plant"; img.alt = ""; img.src = "/img/shroom.png";
        img.onerror = () => { const e = document.createElement("span"); e.className = "plant emo"; e.textContent = "🍄"; img.replaceWith(e); };
        runner.append(img);
        ld.querySelector(".hide").addEventListener("click", () => { ld.hidden = true; });
        document.body.append(ld);
      }
      steps([]); ld.hidden = false;
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
    const busy = on => { go.disabled = on; go.classList.toggle("busy", on); go.querySelector(".lbl").textContent = on ? "조회 중…" : "조회"; overlay(on); };
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
      clearTimeout(timer); clearInterval(tick); if (next) next.textContent = "";
      if (!auto.checked) return;
      const due = Date.now() + AUTO_MS;
      timer = setTimeout(collect, AUTO_MS);
      const show = () => { if (next) next.textContent = "다음 자동 조회 " + left(due - Date.now()); };
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
