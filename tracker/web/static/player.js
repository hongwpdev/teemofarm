// 선수 프로필 팝업(이적·FA 목록, 로스터 카드, 경기 상세 팝업에서 이름을 누르면)
// 목록에 있는 정보로 먼저 열고, 커리어·관련 소식은 /api/player 로 채움. 휴대폰 뒤로 가기는 팝업만 닫음
(function () {
  const dim = document.getElementById("dim"), pbody = document.getElementById("pbody");
  if (!dim) return;
  const esc = t => String(t).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const wikiUrl = page => "https://lol.fandom.com/wiki/" + encodeURIComponent(page.replace(/ /g, "_"));
  let lastFocus = null, seq = 0, pushed = false, mine = false;   // mine: 이 파일이 연 팝업인지(경기 상세 팝업 안에서 그릴 때는 아님)

  // 팝업 안에 선수 프로필을 그림. opts.onClose: [닫기] 버튼, opts.onBack: 맨 위 '← 돌아가기' 버튼(있을 때만)
  function render(p, opts) {
    opts = opts || {};
    const my = ++seq;
    pbody.innerHTML = (opts.onBack ? '<button type="button" class="pback" id="pback">← ' + esc(opts.backLabel || "돌아가기") + "</button>" : "")
      + '<div class="pop_head">' + p.av + '<div><h2 id="pn">' + esc(p.nick) + (p.real ? "<small>" + esc(p.real) + "</small>" : "")
      + '</h2><p class="meta2" id="pmeta">' + esc(p.pos) + '</p><a class="lp" id="plink" href="' + wikiUrl(p.page) + '" target="_blank" rel="noopener">리그피디아에서 사진·프로필 보기</a></div></div>'
      + '<div class="pop_now">' + p.now + "</div>"
      + '<div id="pmore"><section class="pop_sec"><p class="wait">커리어·관련 소식 불러오는 중…</p></section></div>'
      + '<div class="pop_foot"><button class="fav-btn" type="button" id="pfav" aria-pressed="false"></button><button class="btn primary" type="button" id="pclose">닫기</button></div>';
    document.getElementById("pclose").onclick = () => (opts.onClose ? opts.onClose() : close());
    if (opts.onBack) document.getElementById("pback").onclick = () => opts.onBack();
    // 찜하기: 이 브라우저에 저장. 소식 화면 맨 위 '찜한 소식'에 모아 보여 주고, 알림을 켜면 새 오피셜을 알려 줌
    const favs = () => { try { return JSON.parse(localStorage.getItem("favs") || "[]"); } catch (e) { return []; } };
    const fb = document.getElementById("pfav");
    const sync = () => { const on = favs().some(f => f.page === p.page); fb.setAttribute("aria-pressed", on ? "true" : "false"); fb.textContent = on ? "🍄 찜함" : "🍄 찜하기"; };
    fb.onclick = () => {
      let f = favs();
      f = f.some(x => x.page === p.page) ? f.filter(x => x.page !== p.page) : f.concat([{ page: p.page, nick: p.nick, real: p.real || "" }]);
      try { localStorage.setItem("favs", JSON.stringify(f.slice(-30))); } catch (e) {}
      sync();
    };
    sync();
    fetch("/api/player?page=" + encodeURIComponent(p.page)).then(r => r.json()).then(d => {
      if (my !== seq) return;
      const more = document.getElementById("pmore");
      if (d.error) { more.innerHTML = '<section class="pop_sec"><p class="wait">' + esc(d.msg || "정보를 불러오지 못했어요. 잠시 뒤 다시 눌러 보세요") + "</p></section>"; return; }
      document.getElementById("pmeta").textContent = [p.pos, d.country, d.born ? d.born + "년생" : ""].filter(Boolean).join(" · ");
      if (d.wiki) document.getElementById("plink").href = d.wiki;
      let h = "";
      // 기본 정보: 생년월일 · 프로 데뷔(첫 소속) · 시그니처 챔피언 · 공식 SNS
      const ex = d.extra || {}, first = (d.career || []).map(c => c.from).filter(Boolean).sort()[0] || "";
      const cells = [["🎂 생년월일", ex.birth ? ex.birth.replace(/-/g, ".") : ""], ["🚀 프로 데뷔", first ? first.slice(0, 4) + "년" : ""]]
        .filter(x => x[1]).map(x => '<div><small>' + x[0] + "</small><b>" + esc(x[1]) + "</b></div>").join("");
      const champs = (ex.champs || []).length ? '<div class="wide"><small>⚔️ 시그니처 챔피언</small><b>' + ex.champs.map(esc).join(" · ") + "</b></div>" : "";
      if (cells || champs) h += '<section class="pop_sec"><div class="pinfo">' + cells + champs + "</div></section>";
      if ((ex.links || []).length) h += '<section class="pop_sec"><div class="plinks">' + ex.links.map(l =>
        '<a href="' + esc(l.url) + '" target="_blank" rel="noopener">' + esc(l.label) + "</a>").join("") + "</div></section>";
      if (d.career && d.career.length) {
        h += '<section class="pop_sec"><h3>커리어</h3><ul class="career">' + d.career.map(c =>
          '<li><span class="yr">' + esc(c.from) + " – " + esc(c.to) + '</span><span class="tn">'
          + (c.key ? '<img class="logo" src="/logo/' + esc(c.key) + '.png" alt="">' : c.logo ? '<img class="logo" src="' + esc(c.logo) + '" alt="">' : '<i class="nologo"></i>') + esc(c.team) + "</span>"
          + (!c.to ? '<span class="now">현재</span>' : "") + "</li>").join("") + "</ul></section>";
      } else {
        h += '<section class="pop_sec"><h3>커리어</h3><p class="wait">리그피디아에 아직 커리어 기록이 없어요</p></section>';
      }
      h += '<section class="pop_sec"><h3>관련 소식</h3>' + (d.news && d.news.length ? '<ul class="rel_news">' + d.news.map(n =>
        '<li><a href="' + esc(n.url) + '" target="_blank" rel="noopener">' + esc(n.title) + "</a><span>" + esc(n.outlet) + " · " + esc(n.when) + "</span></li>").join("") + "</ul>"
        : '<p class="wait">모아 둔 소식 중에는 아직 없어요</p>') + "</section>";
      more.innerHTML = h;
    }).catch(() => {
      if (my === seq) document.getElementById("pmore").innerHTML = '<section class="pop_sec"><p class="wait">정보를 불러오지 못했어요. 잠시 뒤 다시 눌러 보세요</p></section>';
    });
  }
  function open(p) {
    mine = true;
    render(p);
    lastFocus = document.activeElement;
    dim.classList.add("show"); dim.setAttribute("aria-hidden", "false"); document.body.style.overflow = "hidden";
    dim.querySelector(".x").focus();
    if (!pushed) { try { history.pushState({ pop: 1 }, ""); pushed = true; } catch (e) {} }
  }
  function hide() {
    seq++; mine = false;
    dim.classList.remove("show"); dim.setAttribute("aria-hidden", "true"); document.body.style.overflow = "";
    if (lastFocus) lastFocus.focus();
  }
  function close() { if (pushed) { pushed = false; history.back(); } else hide(); }   // 뒤로 가기 기록을 하나 되돌림 → popstate에서 닫힘
  window.addEventListener("popstate", () => { if (mine && dim.classList.contains("show")) { pushed = false; hide(); } });
  if (window.SPS) window.SPS.renderPlayer = render;      // 경기 상세 팝업(schedule.js)에서 선수 이름을 누를 때

  // 이적·FA 목록의 한 줄 → 팝업 정보
  function fromFaRow(row) {
    const av = row.querySelector(".av"), real = row.querySelector(".nm small");
    return { page: row.dataset.page, nick: row.querySelector(".nk").textContent, real: real ? real.textContent : "",
             pos: av.firstChild.textContent, av: av.outerHTML,
             now: row.querySelector(".st2").outerHTML + '<div class="mv">' + row.querySelector(".mv").innerHTML + '</div><span class="sub">' + esc(row.querySelector(".sub").textContent) + "</span>" };
  }
  // 로스터 카드의 이름 → 팝업 정보
  function fromRoster(el) {
    const card = el.closest(".rc"), color = card.style.getPropertyValue("--tc"), logo = card.querySelector("header img");
    const d = el.dataset;
    return { page: d.page, nick: d.nick, real: d.real, pos: d.pos,
             av: '<span class="av tc" style="--tc:' + color + '">' + esc(d.pos) + (logo ? '<img class="bdg" src="' + logo.src + '" alt="">' : "") + "</span>",
             now: '<span class="st2 s-stay">현재 소속</span><div class="mv"><span class="tm">' + (logo ? logo.outerHTML : "") + esc(card.querySelector("header b").textContent) + '</span></div><span class="sub">' + esc(d.until) + "</span>" };
  }
  function pick(e) {
    const nm = e.target.closest(".fa-row .nm"); if (nm) return fromFaRow(nm.closest(".fa-row"));
    const pn = e.target.closest(".pn[data-page]"); if (pn) return fromRoster(pn);
    return null;
  }
  document.addEventListener("click", e => { const p = pick(e); if (p) { e.preventDefault(); open(p); } });
  document.addEventListener("keydown", e => {
    if (e.key === "Escape" && mine && dim.classList.contains("show")) { close(); return; }
    if (e.key === "Enter" || e.key === " ") { const p = pick(e); if (p) { e.preventDefault(); open(p); } }
  });
  dim.addEventListener("click", e => { if (mine && e.target === dim) close(); });
  dim.querySelector(".x").addEventListener("click", () => { if (mine) close(); });
})();
