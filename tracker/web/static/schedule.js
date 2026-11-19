// 일정·결과: 팀 탭으로 거르기(내 팀이 정해져 있으면 그 팀부터), 내 팀 경기 강조, 스포 방지일 때 점수 눌러서 보기
(function () {
  const tabs = document.getElementById("tabs"); if (!tabs) return;
  const S = window.SPS || { store: { get: () => "" }, MY: "" };
  const my = S.store.get(S.MY);
  const rows = document.querySelectorAll(".mt"), empty = document.getElementById("schEmpty");

  rows.forEach(r => { if (my && (" " + r.dataset.teams + " ").includes(" " + my + " ")) r.classList.add("my"); });
  document.querySelectorAll(".sch-stand tr[data-team]").forEach(tr => { if (my && tr.dataset.team === my) tr.classList.add("my"); });

  function show(t) {
    tabs.querySelectorAll("a").forEach(a => { const on = a.dataset.t === t; a.classList.toggle("on", on); on ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current"); });
    rows.forEach(r => { r.hidden = t !== "all" && !(" " + r.dataset.teams + " ").includes(" " + t + " "); });
    document.querySelectorAll(".sday").forEach(d => { d.hidden = !d.querySelector(".mt:not([hidden])"); });
    document.querySelectorAll(".smore").forEach(d => {
      const n = d.querySelectorAll(".mt:not([hidden])").length, c = d.querySelector(".n");
      d.hidden = !n; if (c) c.textContent = n;
    });
    let any = false;
    document.querySelectorAll(".sblock").forEach(b => { const v = !!b.querySelector(".mt:not([hidden])"); b.hidden = !v; any = any || v; });
    if (empty) empty.hidden = any;
    if (S.centerTabs) S.centerTabs();
  }
  tabs.addEventListener("click", e => {
    const a = e.target.closest("a[data-t]"); if (!a) return;
    e.preventDefault(); show(a.dataset.t);
  });
  if (my && tabs.querySelector('a[data-t="' + my + '"]')) show(my);

  // 스포 방지: 우승 카드는 누르면 보여 줌
  document.addEventListener("click", e => {
    const el = e.target.closest(".sch-champ"); if (el) el.classList.add("lit");
  });

  // ── 경기 상세 팝업: 끝난 경기를 누르면 세트별 밴픽·선수·챔피언·KDA ──
  const dim = document.getElementById("dim"), pbody = document.getElementById("pbody");
  if (!dim) return;
  const LG = document.body.dataset.league;
  const POS = { Top: "탑", Jungle: "정글", Mid: "미드", Bot: "원딜", Support: "서폿" };
  const esc = v => String(v == null ? "" : v).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const num = v => v == null ? "–" : v.toLocaleString("ko-KR");
  const k1 = v => v == null ? "–" : (v / 1000).toFixed(1) + "k";
  // depth: 이 팝업이 쌓은 뒤로 가기 기록 수(경기 1, 그 안에서 선수 프로필을 열면 2). 휴대폰 뒤로 가기: 선수 → 경기 → 닫힘
  let depth = 0, ignorePop = false, mine = false, view = "match", data = null, cur = 0;

  function push() { try { history.pushState({ pop: 1 }, ""); depth++; } catch (e) {} }
  function show() { mine = true; dim.classList.add("show"); dim.setAttribute("aria-hidden", "false"); document.body.style.overflow = "hidden"; dim.querySelector(".x").focus(); }
  function hide() { mine = false; view = "match"; dim.classList.remove("show"); dim.setAttribute("aria-hidden", "true"); document.body.style.overflow = ""; }
  function close() { const n = depth; depth = 0; hide(); if (n) { ignorePop = true; history.go(-n); } }
  function backToMatch() { if (depth > 1) history.back(); else { view = "match"; draw(); } }
  window.addEventListener("popstate", () => {
    if (ignorePop) { ignorePop = false; return; }
    if (!mine || !dim.classList.contains("show")) return;
    if (view === "player" && depth > 1) { depth--; view = "match"; draw(); return; }
    depth = 0; hide();
  });
  dim.addEventListener("click", e => { if (mine && e.target === dim) close(); });
  dim.querySelector(".x").addEventListener("click", () => { if (mine) close(); });
  document.addEventListener("keydown", e => { if (e.key === "Escape" && mine && dim.classList.contains("show")) close(); });

  const team = n => (data.teams && data.teams[n]) || { short: n, logo: "" };
  const logo = n => { const t = team(n); return t.logo ? '<img class="logo" src="' + esc(t.logo) + '" alt="" width="20" height="20">' : '<span class="logo txt" aria-hidden="true">' + esc((t.short || "?")[0]) + "</span>"; };
  const champ = (c, cls) => c && c.img ? '<img class="ch ' + (cls || "") + '" src="' + esc(c.img) + '" alt="' + esc(c.ko) + '" title="' + esc(c.ko) + '" width="32" height="32" loading="lazy">'
    : '<span class="ch none ' + (cls || "") + '" title="' + esc(c ? c.ko : "") + '">' + esc(c && c.ko && c.ko !== "None" ? c.ko[0] : "–") + "</span>";

  function side(g, s) {
    const t = g[s], win = g.win === s;
    const rows = t.players.map((p, i) => '<li><span class="ps">' + esc(POS[p.role] || p.role) + "</span>" + champ(p.champ) +
      '<span class="pn2"><button type="button" class="mpl" data-s="' + s + '" data-i="' + i + '" title="선수 프로필 보기">' + esc(p.name) +
      "</button><small>" + esc(p.champ.ko) + "</small></span>" +
      '<span class="kda"><b>' + p.k + "/" + p.d + "/" + p.a + "</b><small>CS " + num(p.cs) + " · " + k1(p.gold) + "</small></span>" +
      '<span class="dmg" title="챔피언에게 준 피해량">' + num(p.dmg) + "</span></li>").join("");
    const obj = [t.kills != null ? "⚔️ " + t.kills : "", t.towers != null ? "🏰 " + t.towers : "", t.dragons != null ? "🐉 " + t.dragons : "",
      t.barons != null ? "👾 " + t.barons : "", t.gold != null ? "💰 " + k1(t.gold) : ""].filter(Boolean).join(" ");
    return '<section class="gside ' + s + (win ? " won" : "") + '"><header>' + logo(t.team) + "<b>" + esc(team(t.team).short) + "</b>" +
      '<span class="sd">' + (s === "blue" ? "블루" : "레드") + "</span>" + (win ? '<span class="wb">승리</span>' : "") + "</header>" +
      '<p class="obj">' + obj + "</p>" +
      '<div class="bans"><span>밴</span>' + (t.bans.length ? t.bans.map(c => champ(c, "ban")).join("") : "<small>기록 없음</small>") + "</div>" +
      (rows ? '<ul class="plist">' + rows + "</ul>" : '<p class="nodata">선수 기록이 아직 없어요</p>') + "</section>";
  }

  function draw() {
    const m = data.match, gs = data.games || [];
    const head = '<div class="mh"><div class="mh-t">' + logo(m.t1) + "<b>" + esc(team(m.t1).short) + '</b></div><div class="mh-s">' +
      esc(m.s1 || "0") + "<i>:</i>" + esc(m.s2 || "0") + '</div><div class="mh-t r"><b>' + esc(team(m.t2).short) + "</b>" + logo(m.t2) + "</div></div>";
    let body;
    if (!gs.length) body = '<p class="nodata">리그피디아에 이 경기의 세트 기록이 아직 없어요.<br>경기가 끝나고 기록이 올라오기까지 시간이 걸릴 수 있어요.</p>';
    else {
      const g = gs[Math.min(cur, gs.length - 1)];
      const tabs = gs.length > 1 ? '<nav class="gtabs" aria-label="세트">' + gs.map((x, i) => '<button type="button" data-g="' + i + '" class="' + (i === cur ? "on" : "") + '">' + x.n + "세트</button>").join("") + "</nav>" : "";
      const meta = [g.len ? "⏱ " + g.len : "", g.patch ? "패치 " + g.patch : ""].filter(Boolean).join(" · ");
      body = tabs + '<p class="gmeta">' + esc(meta) + (g.vod ? ' <a class="lp" href="' + esc(g.vod) + '" target="_blank" rel="noopener">다시보기</a>' : "") + "</p>" +
        '<div class="gsides">' + side(g, "blue") + side(g, "red") + "</div>";
    }
    pbody.innerHTML = '<div class="mpop"><h2 id="pn" class="sr">경기 상세</h2>' + head + body +
      '<p class="src">기록 출처 리그피디아 · 챔피언 이미지 Riot Games</p></div>';
  }

  pbody.addEventListener("click", e => {
    const b = e.target.closest("button[data-g]"); if (b) { cur = +b.dataset.g; draw(); return; }
    const pl = e.target.closest("button.mpl"); if (pl) openPlayer(pl.dataset.s, +pl.dataset.i);
  });

  // 선수 이름 → 기존 선수 프로필(커리어·관련 소식)을 같은 팝업 안에. 맨 위 '← 경기 기록으로'
  function openPlayer(s, i) {
    if (!window.SPS || !window.SPS.renderPlayer || !data) return;
    const g = data.games[Math.min(cur, data.games.length - 1)], t = g[s], p = t.players[i];
    const tm = team(t.team), pos = POS[p.role] || p.role || "";
    const bdg = tm.logo ? '<img class="bdg" src="' + esc(tm.logo) + '" alt="">' : "";
    const kda = p.k + "/" + p.d + "/" + p.a;
    view = "player"; push();
    window.SPS.renderPlayer({
      page: p.page || p.name, nick: p.name, real: "", pos: pos + " · " + tm.short,
      av: '<span class="av tc" style="--tc:var(--primary)">' + esc(pos) + bdg + "</span>",
      now: '<span class="st2 s-stay">' + g.n + '세트 기록</span><div class="mv">' + champ(p.champ) + " <b>" + esc(p.champ.ko) + "</b> · " +
        esc(kda) + " · CS " + num(p.cs) + "</div>" + '<span class="sub">' + (g.win === s ? "승리" : "패배") + "</span>",
    }, { onClose: close, onBack: backToMatch, backLabel: "경기 기록으로" });
    pbody.parentElement.scrollTop = 0;
  }

  function open(row) {
    row.classList.add("lit");
    data = null; cur = 0; view = "match";
    pbody.innerHTML = '<div class="mpop"><p class="nodata">경기 기록을 불러오는 중… 🍄</p></div>';
    show(); if (!depth) push();
    fetch("/api/match?league=" + encodeURIComponent(LG) + "&id=" + encodeURIComponent(row.dataset.id))
      .then(r => r.json().then(j => ({ ok: r.ok, j })))
      .then(({ ok, j }) => { if (!ok) throw new Error(j.msg || "error"); data = j; draw(); })
      .catch(err => { pbody.innerHTML = '<div class="mpop"><p class="nodata">' + esc(err.message && err.message !== "error" ? err.message : "경기 기록을 불러오지 못했어요. 잠시 뒤 다시 눌러 보세요") + "</p></div>"; });
  }
  document.addEventListener("click", e => { const r = e.target.closest(".mt[data-id]"); if (r) open(r); });
  document.addEventListener("keydown", e => { const r = e.target.closest && e.target.closest(".mt[data-id]"); if (r && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); open(r); } });
})();
