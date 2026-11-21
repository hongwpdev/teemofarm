// 이적·FA: 묶어 보기(포지션·팀·상태)와 필터를 화면에서 바로 적용, 상태는 주소(?g=&s=&p=&team=)에 남김
(function () {
  const S = window.SPS; if (!S) return;
  const TH = JSON.parse(document.getElementById("th").textContent);
  const POSO = ["탑", "정글", "미드", "원딜", "서폿", "감독", "코치"], TEAMO = Object.keys(TH), STO = ["move", "stay", "rm", "fa"];
  const STN = { move: "이적 확정", stay: "잔류 · 재계약", rm: "유력 (기사 추측)", fa: "미정 (FA)" };
  // 상태 칸은 서로 겹치지 않음: 미정 중 기사 추측이 있는 사람(data-rm)은 '유력', 나머지 미정은 '미정'
  const stOf = r => (r.dataset.s === "fa" && r.dataset.rm === "1") ? "rm" : r.dataset.s;
  const list = document.getElementById("falist"), rows = [...list.querySelectorAll(".fa-row")];
  const qs = new URLSearchParams(location.search);
  // 팀: 주소에 있으면 그것, 없으면 내 팀
  let G = qs.get("g") || "p", St = qs.get("s") || "all", P = qs.get("p") || "all", T = qs.get("team") || S.store.get(S.MY) || "all";
  const sumBtns = [...document.querySelectorAll(".sum button")];
  function mark(box, attr, v) {
    const els = [...document.querySelectorAll(box)];
    if (!els.some(e => e.dataset[attr] === v)) v = els[0].dataset[attr];
    els.forEach(e => e.classList.toggle("on", e.dataset[attr] === v));
    return v;
  }
  function render() {
    G = mark("#grp a", "g", G); St = mark(".sum button", "s", St); P = mark("#pos button", "p", P); T = mark("#tabs a", "t", T);
    // 숫자 칸은 고른 팀·포지션 기준으로 다시 셈
    const base = rows.filter(r => (T === "all" || r.dataset.t === T) && (P === "all" || r.dataset.p === P));
    const hit = (r, s) => s === "all" || stOf(r) === s;
    sumBtns.forEach(b => { b.querySelector("b").textContent = base.filter(r => hit(r, b.dataset.s)).length; });
    const vis = base.filter(r => hit(r, St));
    const key = { p: r => r.dataset.p, t: r => r.dataset.t, s: stOf }[G];
    const order = { p: POSO, t: TEAMO, s: STO }[G], head = { p: k => k, t: k => TH[k], s: k => STN[k] }[G];
    list.innerHTML = "";
    for (const k of order) {
      const rs = vis.filter(r => key(r) === k);
      if (!rs.length) continue;
      const c = st => rs.filter(r => stOf(r) === st).length;
      const bd = G === "s" ? "" : '<span class="bd">' + (c("move") ? '<i class="m">이적 ' + c("move") + "</i>" : "")
        + (c("stay") ? '<i class="s">잔류 ' + c("stay") + "</i>" : "") + (c("rm") ? '<i class="r">유력 ' + c("rm") + "</i>" : "")
        + (c("fa") ? '<i class="f">미정 ' + c("fa") + "</i>" : "") + "</span>";
      const li = document.createElement("li");
      li.className = "day grp";
      li.innerHTML = "<span>" + head(k) + bd + '</span><span class="cnt">' + rs.length + "명</span>";
      list.appendChild(li);
      rs.forEach(r => list.appendChild(r));
    }
    if (!list.children.length) list.innerHTML = '<li class="empty"><p>' + (rows.length ? "조건에 맞는 FA가 없어요" : "아직 FA 정보를 모으는 중이에요. [조회]를 눌러 보세요") + "</p></li>";
    const q = new URLSearchParams();
    if (G !== "p") q.set("g", G); if (St !== "all") q.set("s", St); if (P !== "all") q.set("p", P); q.set("team", T);
    try { history.replaceState(history.state, "", location.pathname + "?" + q); } catch (e) {}
  }
  function sel(box, attr, set) {
    document.querySelectorAll(box).forEach(b => b.addEventListener("click", e => { e.preventDefault(); set(b.dataset[attr]); render(); if (box === "#tabs a" && S.centerTabs) S.centerTabs(); }));
  }
  sel("#grp a", "g", v => G = v); sel(".sum button", "s", v => St = v); sel("#pos button", "p", v => P = v); sel("#tabs a", "t", v => T = v);
  render();
  if (S.centerTabs) S.centerTabs();
})();
