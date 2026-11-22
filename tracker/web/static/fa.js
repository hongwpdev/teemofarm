// 이적 시장 선수별: 상태 칩(전체·확정·잔류·유력·미정) + 팀·포지션 고르기. 묶음은 늘 포지션별. 고른 값은 주소(?s=&p=&team=)에 남김
(function () {
  const S = window.SPS; if (!S) return;
  const POSO = ["탑", "정글", "미드", "원딜", "서폿", "감독", "코치"];
  // 상태 칸은 서로 겹치지 않음: 미정 중 기사 추측이 있는 사람(data-rm)은 '유력', 나머지 미정은 '미정'
  const stOf = r => (r.dataset.s === "fa" && r.dataset.rm === "1") ? "rm" : r.dataset.s;
  const list = document.getElementById("falist"), rows = [...list.querySelectorAll(".fa-row")];
  const tsel = document.getElementById("tsel"), psel = document.getElementById("psel");
  const sumBtns = [...document.querySelectorAll(".sum button")];
  const qs = new URLSearchParams(location.search);
  const has = (sel, v) => [...sel.options].some(o => o.value === v);
  // 팀: 주소에 있으면 그것, 없으면 내 팀(목록에 없으면 전체)
  let St = qs.get("s") || "all", P = qs.get("p") || "all", T = qs.get("team") || S.store.get(S.MY) || "all";
  if (!has(tsel, T)) T = "all";
  if (!has(psel, P)) P = "all";
  if (!sumBtns.some(b => b.dataset.s === St)) St = "all";
  function render() {
    tsel.value = T; psel.value = P;
    sumBtns.forEach(b => { const on = b.dataset.s === St; b.classList.toggle("on", on); b.setAttribute("aria-pressed", on ? "true" : "false"); });
    // 숫자 칸은 고른 팀·포지션 기준으로 다시 셈
    const base = rows.filter(r => (T === "all" || r.dataset.t === T) && (P === "all" || r.dataset.p === P));
    const hit = (r, s) => s === "all" || stOf(r) === s;
    sumBtns.forEach(b => { b.querySelector("b").textContent = base.filter(r => hit(r, b.dataset.s)).length; });
    const vis = base.filter(r => hit(r, St));
    list.innerHTML = "";
    for (const k of POSO) {
      const rs = vis.filter(r => r.dataset.p === k);
      if (!rs.length) continue;
      const c = st => rs.filter(r => stOf(r) === st).length;
      const bd = St !== "all" ? "" : '<span class="bd">' + (c("move") ? '<i class="m">확정 ' + c("move") + "</i>" : "")
        + (c("stay") ? '<i class="s">잔류 ' + c("stay") + "</i>" : "") + (c("rm") ? '<i class="r">유력 ' + c("rm") + "</i>" : "")
        + (c("fa") ? '<i class="f">미정 ' + c("fa") + "</i>" : "") + "</span>";
      const li = document.createElement("li");
      li.className = "day grp";
      li.innerHTML = "<span>" + k + bd + '</span><span class="cnt">' + rs.length + "명</span>";
      list.appendChild(li);
      rs.forEach(r => list.appendChild(r));
    }
    if (!list.children.length) list.innerHTML = '<li class="empty"><p>' + (rows.length ? "조건에 맞는 FA가 없어요" : "아직 FA 정보를 모으는 중이에요") + "</p></li>";
    const q = new URLSearchParams();
    if (St !== "all") q.set("s", St); if (P !== "all") q.set("p", P); q.set("team", T);
    try { history.replaceState(history.state, "", location.pathname + "?" + q); } catch (e) {}
  }
  sumBtns.forEach(b => b.addEventListener("click", e => { e.preventDefault(); St = b.dataset.s; render(); }));
  tsel.addEventListener("change", () => { T = tsel.value; render(); });
  psel.addEventListener("change", () => { P = psel.value; render(); });
  render();
})();
