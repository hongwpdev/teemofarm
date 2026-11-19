// 스토브리그 > 예측: FA 행선지 투표. 이 브라우저 번호(수다방과 같은 번호)로 한 사람 한 표, 다시 누르면 바꿈
(function () {
  const list = document.getElementById("vlist"); if (!list) return;
  const S = (window.SPS && window.SPS.store) || { get: () => "", set: () => {} };
  let cid = S.get("chatCid");
  if (!/^[A-Za-z0-9_-]{8,40}$/.test(cid || "")) {
    cid = Array.from({ length: 24 }, () => "abcdefghijklmnopqrstuvwxyz0123456789"[Math.floor(Math.random() * 36)]).join("");
    S.set("chatCid", cid);
  }
  const label = {};
  list.querySelector(".vopts").querySelectorAll("button").forEach(b => { label[b.dataset.c] = b.textContent.trim(); });

  function show(card, tally, mine) {
    const res = card.querySelector(".vres"), n = Object.values(tally || {}).reduce((a, b) => a + b, 0);
    card.querySelectorAll(".vopts button").forEach(b => b.classList.toggle("on", b.dataset.c === mine));
    if (!mine || !n) { res.hidden = true; return; }
    const rows = Object.entries(tally).sort((a, b) => b[1] - a[1]).slice(0, 4).map(([c, v]) => {
      const pct = Math.round(100 * v / n);
      return '<p class="' + (c === mine ? "me" : "") + '"><span>' + (label[c] || c) + '</span><i style="--w:' + pct + '%"></i><b>' + pct + "%</b></p>";
    }).join("");
    res.innerHTML = rows + '<small>' + n + "표 · 다른 팀을 누르면 바꿀 수 있어요</small>";
    res.hidden = false;
  }

  let mineAll = {}, tallyAll = {};
  fetch("/api/votes?cid=" + encodeURIComponent(cid)).then(r => r.json()).then(d => {
    tallyAll = d.tally || {}; mineAll = d.mine || {};
    list.querySelectorAll(".vcard").forEach(c => show(c, tallyAll[c.dataset.page], mineAll[c.dataset.page]));
  }).catch(() => {});

  list.addEventListener("click", async e => {
    const b = e.target.closest(".vopts button"); if (!b) return;
    const card = b.closest(".vcard"), page = card.dataset.page;
    card.classList.add("busy");
    try {
      const res = await fetch("/api/vote", { method: "POST", headers: { "Content-Type": "application/json" },
                                             body: JSON.stringify({ page, choice: b.dataset.c, cid }) });
      const d = await res.json();
      if (d.ok) { mineAll[page] = b.dataset.c; tallyAll[page] = d.tally; show(card, d.tally, b.dataset.c); }
      else { const r = card.querySelector(".vres"); r.innerHTML = "<small>" + (d.msg || "투표하지 못했어요") + "</small>"; r.hidden = false; }
    } catch (err) {} finally { card.classList.remove("busy"); }
  });
})();
