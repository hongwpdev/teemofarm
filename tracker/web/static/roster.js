// 로스터: 내 팀 카드를 맨 앞에 두고 강조
(function () {
  const S = window.SPS; if (!S) return;
  const my = S.store.get(S.MY), grid = document.getElementById("rgrid");
  if (!my || !grid) return;
  const card = grid.querySelector('.rc[data-team="' + my + '"]');
  if (card) { card.classList.add("mine"); grid.prepend(card); }
})();
