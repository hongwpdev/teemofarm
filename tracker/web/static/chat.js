// 수다방: 사이트 전체 대화방(로그인 없음). 닉네임은 '챔피언 이름+숫자 4자리'로 자동, 바꿀 수 있음(이 브라우저에만 기억)
(function () {
  const S = window.SPS && window.SPS.store || { get: () => "", set: () => {} };
  const CHAMPS = ("가렌 갈리오 갱플랭크 그라가스 그레이브즈 나미 나서스 노틸러스 녹턴 누누 니달리 다리우스 다이애나 드레이븐 라이즈 람머스 럭스 럼블 레넥톤 " +
    "레오나 렉사이 렝가 루시안 룰루 르블랑 리신 리븐 리산드라 마스터이 마오카이 말자하 모르가나 문도 미스포츈 바드 바루스 바이 베이가 블라디미르 " +
    "블리츠크랭크 빅토르 뽀삐 사이온 사일러스 세나 세주아니 소나 소라카 쉔 쉬바나 스웨인 신지드 신짜오 쓰레쉬 아리 아무무 아지르 아칼리 아펠리오스 " +
    "알리스타 애니 애니비아 애쉬 야스오 에코 엘리스 오공 오른 오리아나 올라프 요네 요릭 우디르 우르곳 워윅 유미 이렐리아 이블린 이즈리얼 일라오이 " +
    "자르반 자야 자이라 자크 잔나 잭스 제드 제라스 제리 제이스 조이 직스 진 질리언 징크스 초가스 카르마 카밀 카사딘 카서스 카시오페아 카이사 " +
    "카직스 카타리나 칼리스타 케넨 케이틀린 케인 케일 코그모 코르키 퀸 클레드 킨드레드 타릭 탈론 탈리야 탐켄치 트런들 트리스타나 트린다미어 " +
    "트위스티드페이트 트위치 티모 파이크 판테온 피들스틱 피오라 피즈 하이머딩거 헤카림 흐웨이").split(" ");
  const rand = n => Math.floor(Math.random() * n);
  let cid = S.get("chatCid");
  if (!/^[A-Za-z0-9_-]{8,40}$/.test(cid)) {
    cid = Array.from({ length: 24 }, () => "abcdefghijklmnopqrstuvwxyz0123456789"[rand(36)]).join("");
    S.set("chatCid", cid);
  }
  let name = S.get("chatName");
  if (!name) { name = CHAMPS[rand(CHAMPS.length)] + String(rand(10000)).padStart(4, "0"); S.set("chatName", name); }

  const esc = s => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const ICON = '<span class="ico" aria-hidden="true">💬</span>';
  document.body.insertAdjacentHTML("beforeend",
    '<button class="chat-fab" type="button" id="cfab" aria-label="수다방 열기">' + ICON + '수다방<span class="n" hidden></span></button>' +
    '<div class="chat-dim" id="cdim" hidden></div>' +
    '<section class="chat" id="chat" hidden aria-label="수다방">' +
    '<header><span class="grab"></span><div><b>버섯농장 수다방</b><small><i></i><span id="con">연결 중…</span></small></div>' +
    '<button class="x" id="cx" type="button" aria-label="닫기">×</button></header>' +
    '<div class="me" id="cme"></div>' +
    '<div class="msgs" id="msgs" aria-live="polite"></div>' +
    '<p class="rule">로그인 없이 누구나 볼 수 있어요 · 최근 200개만 보관 · 도배·욕설은 가려져요</p>' +
    '<form id="cf"><input id="ci" maxlength="200" placeholder="메시지 입력 (200자까지)" autocomplete="off" enterkeyhint="send">' +
    '<button type="submit">보내기</button></form></section>');
  const $ = id => document.getElementById(id);
  const fab = $("cfab"), box = $("chat"), dim = $("cdim"), list = $("msgs"), input = $("ci"), badge = fab.querySelector(".n");
  const seenRaw = S.get("chatSeen");
  let last = 0, seen = +seenRaw || 0, isOpen = false, timer = null, loaded = false;

  function meRow(edit) {
    $("cme").innerHTML = edit
      ? '내 이름 <input id="cn" maxlength="12" value="' + esc(name) + '"><button type="button" id="cns">저장</button>'
      : '내 이름 <b>' + esc(name) + '</b><button type="button" id="cne">바꾸기</button>';
    if (edit) {
      const n = $("cn"); n.focus(); n.select();
      const save = () => { const v = n.value.trim().replace(/\s+/g, " ").slice(0, 12); if (v) { name = v; S.set("chatName", v); } meRow(false); };
      $("cns").onclick = save;
      n.onkeydown = e => { if (e.key === "Enter") { e.preventDefault(); save(); } if (e.key === "Escape") meRow(false); };
    } else $("cne").onclick = () => meRow(true);
  }
  const when = iso => {
    const d = new Date(iso), m = Math.floor((Date.now() - d) / 60000);
    if (m < 1) return "방금"; if (m < 60) return m + "분 전";
    return d.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Seoul" });
  };
  function add(m) {
    if (list.querySelector('[data-id="' + m.id + '"]')) return;
    const d = document.createElement("div");
    d.className = "msg" + (m.mine ? " mine" : ""); d.dataset.id = m.id; d.dataset.at = m.at;
    d.innerHTML = '<span class="who">' + (m.mine ? "" : esc(m.name)) + '<em></em></span><span class="bub"></span>';
    d.querySelector("em").textContent = when(m.at);
    d.querySelector(".bub").textContent = m.text;
    list.append(d);
  }
  function setBadge() {
    const n = Math.max(0, last - seen);
    badge.hidden = isOpen || !n || !loaded; badge.textContent = n > 99 ? "99+" : n;
  }
  async function poll() {
    clearTimeout(timer);
    try {
      const r = await (await fetch("/api/chat?cid=" + cid + "&after=" + (isOpen && list.childElementCount ? last : (isOpen ? 0 : last)))).json();
      $("con").textContent = "지금 " + r.online + "명 보는 중";
      if (!loaded) {   // 처음 온 사람은 예전 메시지를 '안 읽음'으로 세지 않음(그 기준을 기억해 둬서 다른 화면으로 가도 유지)
        loaded = true;
        if (seenRaw === "") { seen = r.last; S.set("chatSeen", String(seen)); }
      }
      if (isOpen) {
        const atEnd = list.scrollHeight - list.scrollTop - list.clientHeight < 60;
        r.msgs.forEach(add);
        if (!list.childElementCount) list.innerHTML = '<div class="sys empty">아직 대화가 없어요. 첫 마디를 남겨 보세요!</div>';
        else { const e = list.querySelector(".sys.empty"); if (e) e.remove(); }
        list.querySelectorAll(".msg em").forEach(e => { e.textContent = when(e.closest(".msg").dataset.at); });
        if (atEnd || r.msgs.some(m => m.mine)) list.scrollTop = list.scrollHeight;
        seen = r.last; S.set("chatSeen", String(seen));
      }
      last = r.last;
    } catch (e) { $("con").textContent = "연결이 잠시 끊겼어요"; }
    setBadge();
    timer = setTimeout(poll, document.hidden ? 60000 : (isOpen ? 3000 : 10000));
  }
  function open(on) {
    isOpen = on; box.hidden = !on; dim.hidden = !on; fab.hidden = on;
    document.documentElement.classList.toggle("chat-open", on);
    if (on) { list.innerHTML = ""; meRow(false); poll().then(() => { list.scrollTop = list.scrollHeight; }); if (matchMedia("(min-width:720px)").matches) input.focus(); }
    else { setBadge(); }
  }
  fab.onclick = () => open(true);
  $("cx").onclick = () => open(false);
  dim.onclick = () => open(false);
  document.addEventListener("keydown", e => { if (e.key === "Escape" && isOpen && !document.querySelector(".dim.show")) open(false); });
  document.addEventListener("visibilitychange", () => { if (!document.hidden) poll(); });
  $("cf").onsubmit = async e => {
    e.preventDefault();
    const text = input.value.trim(); if (!text) return;
    const btn = e.target.querySelector("button"); btn.disabled = true;
    try {
      const res = await fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ cid, name, text }) });
      const r = await res.json();
      if (res.ok) { input.value = ""; await poll(); list.scrollTop = list.scrollHeight; }
      else note(r.msg || "보내지 못했어요");
    } catch (err) { note("서버에 연결할 수 없어요"); }
    btn.disabled = false; input.focus();
  };
  function note(t) {
    const d = document.createElement("div"); d.className = "sys warn"; d.textContent = t; list.append(d);
    list.scrollTop = list.scrollHeight; setTimeout(() => d.remove(), 4000);
  }
  poll();
})();
