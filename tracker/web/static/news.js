// 소식: 필터 접기, 기간·출처 이동, 상대 시간, 내 팀 정하기
(function () {
  const S = window.SPS; if (!S) return;
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
  // 기간·출처 선택 → 해당 주소로 이동('직접 선택'은 날짜 칸을 엶)
  const period = document.getElementById("period"), dates = document.getElementById("dates");
  if (period) period.addEventListener("change", () => {
    if (period.value === "custom") { dates.classList.add("show"); dates.querySelector("input").focus(); }
    else location.href = period.value;
  });
  const src = document.getElementById("src");
  if (src) src.addEventListener("change", e => { location.href = e.target.value; });

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
  relAll(); setInterval(relAll, 60000);

  // ── 시야: 안 읽은 최신 소식(24시간)은 안개, 누르면 읽음 → 환하게. 루머·스포 방지 안개는 한 번 누르면 걷힘 ──
  const root = document.documentElement;
  const read = new Set((S.store.get("readIds") || "").split("|").filter(Boolean));
  const items = Array.from(document.querySelectorAll(".list > .item[data-id]"));
  items.forEach(li => {
    if (read.has(li.dataset.id)) li.classList.add("read");
    else if (Date.now() - +li.dataset.ts < 864e5) li.classList.add("unread");
  });
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

  // ── 찜한 소식: 선수 팝업에서 찜한 선수 이름이 들어간 소식을 맨 위에 모음 + 새 오피셜 알림 ──
  let favs = [];
  try { favs = JSON.parse(localStorage.getItem("favs") || "[]"); } catch (e) {}
  const listCard = document.querySelector(".tabs-wrap") && document.querySelector(".tabs-wrap").closest(".card");
  if (favs.length && listCard) {
    const escH = t => String(t).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    fetch("/api/people").then(r => r.json()).catch(() => []).then(people => {
      const ko = {}; (people || []).forEach(p => { ko[p.page] = p.ko; });
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
  const box = document.getElementById("myteam"), tabs = document.getElementById("tabs");
  if (!box || !tabs) return;
  const cur = (tabs.querySelector("a.on") || {}).dataset || {};
  const teamEl = k => tabs.querySelector('a[data-t="' + k + '"]');
  function draw() {
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
  box.addEventListener("click", e => {
    if (e.target.closest("button[data-off]")) { S.store.set("myHintOff", "1"); draw(); return; }
    const b = e.target.closest("button[data-set]"); if (!b) return;
    S.store.set(S.MY, b.dataset.set); draw(); if (S.markMy) S.markMy();
  });
  draw();
})();
