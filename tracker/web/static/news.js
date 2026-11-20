// 소식: 필터 접기, 기간·출처 이동, 상대 시간, 내 팀 정하기
// 보기(전체·스토브리그·오피셜)·팀·기간·출처를 바꿀 때는 새 주소의 화면(서버가 그린 HTML)을 받아 소식 칸(.layout)만 바꿔 끼움:
// 주소·뒤로 가기·검색 노출은 그대로, 깜빡임과 맨 위로 튀는 것만 없앰. 안 되면(오래된 브라우저·오류) 보통 이동
(function () {
  const S = window.SPS; if (!S) return;
  const root = document.documentElement;
  const read = new Set((S.store.get("readIds") || "").split("|").filter(Boolean));

  // ── 한 번만 거는 것(문서 전체에서 받음) ──
  // 같은 소식 묶음: '관련 보도 N건 더보기'를 누르면 펼침
  document.addEventListener("click", e => {
    const b = e.target.closest(".sib-btn"); if (!b) return;
    const list = b.nextElementSibling, open = b.getAttribute("aria-expanded") !== "true";
    b.setAttribute("aria-expanded", open ? "true" : "false"); list.hidden = !open;
    b.firstChild.textContent = (open ? "관련 보도 접기" : "관련 보도 " + list.children.length + "건 더보기");
  });

  // 상대 시간은 1분마다 갱신
  const rel = ts => {
    const m = Math.floor((Date.now() - ts) / 60000);
    if (m < 1) return "방금";
    if (m < 60) return m + "분 전";
    if (m < 1440) return Math.floor(m / 60) + "시간 전";
    return Math.floor(m / 1440) + "일 전";
  };
  const relAll = () => document.querySelectorAll(".rel[data-ts]").forEach(el => { el.textContent = rel(+el.dataset.ts); });
  setInterval(relAll, 60000);

  // 시야: 안 읽은 최신 소식(24시간)은 안개, 누르면 읽음 → 환하게. 루머·스포 방지 안개는 한 번 누르면 걷힘
  document.addEventListener("click", e => {
    const a = e.target.closest(".list > .item > a.row"); if (!a) return;
    const li = a.parentNode, hover = matchMedia("(hover:hover)").matches;
    const spoiled = root.dataset.spoiler === "on" && (li.classList.contains("spo") || li.classList.contains("kd-rumor"));
    if (!li.classList.contains("lit") && (spoiled || (li.classList.contains("lv-1") && !hover))) {
      e.preventDefault(); li.classList.add("lit"); return;          // 첫 번째 누름은 안개 걷기, 두 번째에 기사 열기
    }
    li.classList.add("lit"); li.classList.remove("unread"); li.classList.add("read");
    read.add(li.dataset.id); S.store.set("readIds", Array.from(read).slice(-600).join("|"));
  });

  // 내 팀 줄의 버튼
  document.addEventListener("click", e => {
    const box = e.target.closest("#myteam"); if (!box) return;
    if (e.target.closest("button[data-off]")) { S.store.set("myHintOff", "1"); drawMy(); return; }
    const b = e.target.closest("button[data-set]"); if (!b) return;
    S.store.set(S.MY, b.dataset.set); drawMy(); if (S.markMy) S.markMy();
  });

  let people = null;          // 찜한 소식용 선수 이름(한 번만 받음)
  const getPeople = () => people || (people = fetch("/api/people").then(r => r.json()).catch(() => []));

  // ── 화면을 그릴 때마다(처음 + 소식 칸을 바꿔 끼운 뒤) ──
  function init() {
    // 필터 접기/펴기(이 브라우저 탭에서 기억)
    const fbar = document.getElementById("fbar"), fbtn = document.getElementById("fbtn");
    if (fbar && fbtn) {
      try { if (sessionStorage.getItem("fbarOpen") === "1") fbar.classList.add("open"); } catch (e) {}
      const sync = () => fbtn.setAttribute("aria-expanded", fbar.classList.contains("open") ? "true" : "false");
      sync();
      fbtn.addEventListener("click", () => {
        fbar.classList.toggle("open"); sync();
        try { sessionStorage.setItem("fbarOpen", fbar.classList.contains("open") ? "1" : ""); } catch (e) {}
      });
    }
    // 기간·출처 선택 → 그 주소로('직접 선택'은 날짜 칸을 엶)
    const period = document.getElementById("period"), dates = document.getElementById("dates");
    if (period) period.addEventListener("change", () => {
      if (period.value === "custom") { dates.classList.add("show"); dates.querySelector("input").focus(); }
      else go(period.value);
    });
    const src = document.getElementById("src");
    if (src) src.addEventListener("change", e => go(e.target.value));

    relAll();
    const items = Array.from(document.querySelectorAll(".list > .item[data-id]"));
    items.forEach(li => {
      if (read.has(li.dataset.id)) li.classList.add("read");
      else if (Date.now() - +li.dataset.ts < 864e5) li.classList.add("unread");
    });
    favBox(items);
    drawMy();
  }

  // 찜한 소식: 선수 팝업에서 찜한 선수 이름이 들어간 소식을 맨 위에 모음 + 새 오피셜 알림
  function favBox(items) {
    let favs = [];
    try { favs = JSON.parse(localStorage.getItem("favs") || "[]"); } catch (e) {}
    const listCard = document.querySelector(".tabs-wrap") && document.querySelector(".tabs-wrap").closest(".card");
    if (!favs.length || !listCard) return;
    const escH = t => String(t).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    getPeople().then(list => {
      if (!listCard.isConnected) return;                       // 그새 소식 칸이 또 바뀜
      const ko = {}; (list || []).forEach(p => { ko[p.page] = p.ko; });
      const terms = favs.map(f => [f.nick, ko[f.page], f.real].filter(Boolean));
      const hit = li => { const t = li.querySelector(".tit").textContent.toLowerCase(); return terms.some(ts => ts.some(w => t.indexOf(w.toLowerCase()) >= 0)); };
      const mine = items.filter(hit);
      const box = document.createElement("section");
      box.className = "card favbox";
      const canNotify = "Notification" in window;
      box.innerHTML = '<h3>찜한 소식' + (canNotify && Notification.permission !== "granted" ? '<button type="button" class="fav-btn" id="fnoti">알림 켜기</button>' : "") + "</h3>"
        + '<div class="chipz">' + favs.map(f => "<span>" + escH(f.nick) + "</span>").join("") + "</div>"
        + (mine.length ? "<ul>" + mine.slice(0, 6).map(li => '<li><a href="' + escH(li.querySelector("a.row").href) + '" target="_blank" rel="noopener">'
          + escH(li.querySelector(".tit").firstChild.textContent) + "<small>" + escH((li.querySelector(".rel") || {}).textContent || "") + "</small></a></li>").join("") + "</ul>"
          : '<p class="empty">지금 보이는 소식 중엔 아직 없어요</p>');
      listCard.parentNode.insertBefore(box, listCard);
      const nb = document.getElementById("fnoti");
      if (nb) nb.onclick = () => Notification.requestPermission().then(() => { nb.remove(); });
      // 알림: 지난번 확인 뒤 새로 들어온 찜 선수 오피셜(처음엔 기준만 잡음)
      const last = +S.store.get("favNotified") || 0, newest = Math.max(0, ...items.map(li => +li.dataset.ts));
      if (last && canNotify && Notification.permission === "granted") {
        mine.filter(li => li.classList.contains("kd-official") && +li.dataset.ts > last).slice(0, 3).forEach(li => {
          try { new Notification("🍄 찜한 선수 오피셜", { body: li.querySelector(".tit").firstChild.textContent, icon: "/img/shroom.png" }); } catch (e) {}
        });
      }
      if (newest > last) S.store.set("favNotified", String(newest));
    });
  }

  // 내 팀: 지금 보는 팀을 내 팀으로 / 해제
  function drawMy() {
    const box = document.getElementById("myteam"), tabs = document.getElementById("tabs");
    if (!box || !tabs) return;
    const cur = (tabs.querySelector("a.on") || {}).dataset || {};
    const teamEl = k => tabs.querySelector('a[data-t="' + k + '"]');
    const my = S.store.get(S.MY), t = cur.t;
    let h = "";
    if (my && teamEl(my)) {
      const a = teamEl(my);
      h = '내 팀 ' + (a.querySelector("img") ? a.querySelector("img").outerHTML : "") + "<b>" + a.querySelector("span").textContent + "</b> · 다음에 들어와도 먼저 보여요";
      if (t && t !== "all" && t !== my && teamEl(t)) h += ' <button type="button" data-set="' + t + '">' + teamEl(t).querySelector("span").textContent + "로 바꾸기</button>";
      h += ' <button type="button" data-set="">해제</button>';
    } else if (t && t !== "all" && t !== "lck" && teamEl(t)) {
      h = '<button type="button" data-set="' + t + '">★ ' + teamEl(t).querySelector("span").textContent + "을(를) 내 팀으로 정하기</button> · 다음에 들어오면 바로 이 팀이 보여요";
    } else if (!S.store.get("myHintOff")) {          // 처음 온 사람용 안내: ×로 닫으면 다시 안 보임
      h = "팀 탭을 고른 뒤 내 팀으로 정해 두면, 다음에 들어올 때 바로 그 팀이 보여요"
        + ' <button type="button" class="hint-x" data-off="1" aria-label="안내 닫기">×</button>';
    }
    box.innerHTML = h;
    box.hidden = !h;
  }

  // ── 소식 칸만 바꿔 끼우기 ──
  let shown = location.href, ctl = null;
  try { history.replaceState(Object.assign({}, history.state, { tfNews: 1 }), ""); } catch (e) {}

  async function go(url, push = true) {
    const cur = document.querySelector("main .layout");
    if (!cur || !window.fetch || !window.DOMParser || !window.AbortController) { location.href = url; return; }
    if (ctl) ctl.abort();                            // 연달아 누르면 앞의 요청은 버림
    ctl = new AbortController();
    const y = window.scrollY;
    cur.classList.add("is-loading"); cur.setAttribute("aria-busy", "true");
    try {
      const res = await fetch(url, { signal: ctl.signal, credentials: "same-origin" });
      if (!res.ok) throw new Error("HTTP " + res.status);
      const doc = new DOMParser().parseFromString(await res.text(), "text/html");
      const next = doc.querySelector("main .layout");
      if (!next || doc.body.dataset.sec !== "news") throw new Error("not news");
      // 독버섯 심기 칸과 [조회]·자동 단추는 지금 것을 그대로 옮겨 씀(그 칸의 스크립트·타이머가 붙어 있음)
      const tf = document.getElementById("tf"), ntf = next.querySelector("#tf");
      if (ntf && !tf) throw new Error("farm needs a full load");
      if (tf && ntf) {
        ntf.replaceWith(tf);
        const d0 = document.getElementById("tf-data"), d1 = next.querySelector("#tf-data");
        if (d0 && d1) d1.replaceWith(d0);
      }
      for (const sel of [".rfr", "#msg"]) {
        const a = document.querySelector(sel), b = next.querySelector(sel);
        if (a && b) b.replaceWith(a);
      }
      cur.replaceWith(next);
      document.title = doc.title;
      if (push) history.pushState({ tfNews: 1 }, "", url);
      shown = location.href;
      window.scrollTo(0, Math.min(y, document.documentElement.scrollHeight - window.innerHeight));   // 맨 위로 튀지 않게
      init();
      if (S.initTabs) S.initTabs();
      if (S.keepQs) S.keepQs();
      document.dispatchEvent(new CustomEvent("tf:region-updated", { detail: { url } }));
    } catch (e) {
      if (e && e.name === "AbortError") return;
      location.href = url;                           // 안 되면 보통 이동
    }
  }

  // 소식 칸 안의 같은 화면(/lck?…) 링크: 보기·팀 탭·'전체 소식 보기' 등. 기사·독버섯 칸·선수 이름은 건드리지 않음
  document.addEventListener("click", e => {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    const a = e.target.closest("main .layout a[href]");
    if (!a || a.target || a.hasAttribute("download") || a.closest(".item > a.row, .sib-list, #tf, .pn, .nm, .aff")) return;
    const u = new URL(a.href, location.href);
    if (u.origin !== location.origin || u.pathname !== location.pathname || u.hash) return;
    e.preventDefault();
    go(u.href);
  });
  // 뒤로·앞으로: 주소가 바뀐 경우만(선수 팝업이 쌓는 같은 주소의 기록은 player.js가 처리)
  window.addEventListener("popstate", () => { if (location.href !== shown) go(location.href, false); });

  init();
})();
