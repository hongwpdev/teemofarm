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

  // 스포 방지: 흐린 점수를 누르면 그 경기만 보여 줌
  document.addEventListener("click", e => {
    const el = e.target.closest(".mt.done, .sch-champ"); if (el) el.classList.add("lit");
  });
})();
