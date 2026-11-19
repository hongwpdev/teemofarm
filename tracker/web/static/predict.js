// 스토브리그 > 행선지 맞히기: 선수 줄의 [고르기]를 누르면 팀 고르는 창이 뜸. 이 브라우저 번호(수다방과 같은 번호)로 한 사람 한 표
(function () {
  const rows = [...document.querySelectorAll(".vrow")], sheet = document.getElementById("vsheet");
  if (!rows.length || !sheet) return;
  const S = (window.SPS && window.SPS.store) || { get: () => "", set: () => {} };
  let cid = S.get("chatCid");
  if (!/^[A-Za-z0-9_-]{8,40}$/.test(cid || "")) {
    cid = Array.from({ length: 24 }, () => "abcdefghijklmnopqrstuvwxyz0123456789"[Math.floor(Math.random() * 36)]).join("");
    S.set("chatCid", cid);
  }
  const label = {};
  sheet.querySelectorAll(".vopts button").forEach(b => { label[b.dataset.c] = b.textContent.trim(); });
  let tally = {}, mine = {}, cur = null;

  function paint(row) {
    const page = row.dataset.page, t = tally[page] || {}, n = Object.values(t).reduce((a, b) => a + b, 0);
    const top = Object.entries(t).sort((a, b) => b[1] - a[1])[0];
    row.querySelector(".vtop").textContent = top ? `1위 ${label[top[0]] || top[0]} ${Math.round(100 * top[1] / n)}% · ${n}표` : "";
    const btn = row.querySelector(".vpick"), m = mine[page];
    btn.textContent = m ? `내 선택 ${label[m] || m}` : "고르기";
    btn.classList.toggle("on", !!m);
  }

  fetch("/api/votes?cid=" + encodeURIComponent(cid)).then(r => r.json()).then(d => {
    tally = d.tally || {}; mine = d.mine || {};
    rows.forEach(paint);
  }).catch(() => {});

  document.addEventListener("click", e => {
    const b = e.target.closest(".vpick"); if (!b) return;
    cur = b.closest(".vrow");
    document.getElementById("vs-nick").textContent = cur.dataset.nick;
    sheet.querySelectorAll(".vopts button").forEach(x => x.classList.toggle("on", x.dataset.c === mine[cur.dataset.page]));
    sheet.querySelector(".vs-n").textContent = "발표 전까지는 몇 번이든 바꿀 수 있어요.";
    if (typeof sheet.showModal === "function") sheet.showModal(); else sheet.setAttribute("open", "");
  });
  sheet.addEventListener("click", async e => {
    if (e.target === sheet) { sheet.close(); return; }          // 바깥(어두운 곳)을 누르면 닫기
    const b = e.target.closest(".vopts button"); if (!b || !cur) return;
    const page = cur.dataset.page;
    sheet.classList.add("busy");
    try {
      const res = await fetch("/api/vote", { method: "POST", headers: { "Content-Type": "application/json" },
                                             body: JSON.stringify({ page, choice: b.dataset.c, cid }) });
      const d = await res.json();
      if (d.ok) { mine[page] = b.dataset.c; tally[page] = d.tally; paint(cur); sheet.close(); }
      else sheet.querySelector(".vs-n").textContent = d.msg || "투표하지 못했어요. 잠시 뒤 다시 눌러 주세요.";
    } catch (err) {
      sheet.querySelector(".vs-n").textContent = "서버에 연결하지 못했어요.";
    } finally { sheet.classList.remove("busy"); }
  });
})();
