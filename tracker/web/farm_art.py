"""독버섯 심기 도트 그림(12칸 격자) — 서버(첫 화면)와 static/farm.js가 같이 쓰는 한 벌.
서버는 이 그림으로 첫 HTML을 그리고, 같은 데이터를 #tf-data에 넣어 farm.js가 그대로 씀(그림을 두 군데서 따로 고치지 않게)."""
from html import escape

SPR = {
    # 실눈 웃음(^ ^) + 볼 + 갓 위 밝은 점. 수확 카드(farm.js shot)도 이 그림 그대로
    "shroom": ["....RRRR....", "..RRLLRRRR..", ".RRWWRRRRWR.", "RRWWRRRRRRRR", "RRRRRRRWWRRR", "RRRRRRRWWRRR", ".RRRRRRRRRR.",
               "..SSSSSSSS..", "..SSESSSES..", "..SESESESE..", "..PSSMMSSP..", "...SSSSSS..."],
    "happy": ["....RRRR....", "..RRRRRRRR..", ".RRWWRRRRWR.", "RRWWRRRRRRRR", "RRRRRRRWWRRR", "RRRRRRRWWRRR", ".RRRRRRRRRR.",
              "...SESSESS..", "...ESESESE..", "...SSSSSS...", "...SMMMMS...", "....SSSS...."],
    "gold": ["....AAAA....", "..AAYYAAAA..", ".AAYYAAAAYA.", "AAYYAAAAAAAA", "AAAAAAAYYAAA", "AAAAAAAYYAAA", ".AAAAAAAAAA.",
             "..SSSSSSSS..", "..SSESSSES..", "..SESESESE..", "..PSSMMSSP..", "...SSSSSS..."],
    "burnt": ["....CCCC....", "..CCCCCCCC..", ".CCqqCCCCqC.", "CCqqCCCCCCCC", "CCCCCCCqqCCC", "CCCCCCCqqCCC", ".CCCCCCCCCC.",
              "...TTTTTT...", "...TXTTXT...", "...TTTTTT...", "...TTMMTT...", "....TTTT...."],
    "tile": ["gGgGGgGGgGgG", "GGGgGGGgGGGG", "DdDDDdDDDDdD", "DDDDdDDdDDDD", "dDDDDDDDdDDD", "DDdDDDDDDDdD"],
    "hole": ["gGgGGgGGgGgG", "GGGgGGGgGGGG", "DdDDKKKKDDdD", "DDDKKKKKKDDD", "dDDDKKKKdDDD", "DDdDDDDDDDdD"],
}
# 글자 = 색: R 갓 · L 갓 위 밝은 점 · W 흰 점 · S 기둥 · E 눈 · M 입 · P 볼 · A/Y 황금 · C/q/X/T 독버섯(그을림) · g/G 잔디 · D/d 흙 · K 구멍
COL = {"R": "var(--shroom)", "W": "#fff", "S": "var(--stem)", "E": "#1e2022", "M": "#7a2e2a", "A": "#f2b705", "Y": "#fff3b0",
       "C": "#4a3d55", "q": "#8b8296", "X": "#2a1f33", "T": "#9b8f86", "g": "#5fbf3f", "G": "#4c9a33", "D": "#8a5a3b",
       "d": "#6f472d", "K": "#4e3220",
       "P": "#fb7185", "L": "#ff9a8f"}


def px(kind: str, w: float) -> str:
    g = SPR[kind]
    W, H = len(g[0]), len(g)
    rects = "".join(f'<rect x="{x}" y="{y}" width="1.02" height="1.02" fill="{COL[ch]}"/>'
                    for y, row in enumerate(g) for x, ch in enumerate(row) if ch != ".")
    return (f'<svg class="tf-px" viewBox="0 0 {W} {H}" width="{w:g}" height="{w * H / W:g}" shape-rendering="crispEdges" '
            f'aria-hidden="true">{rects}</svg>')


def plot(what, size: int, cls: str = "") -> str:
    """밭 한 칸: 흙 타일 위에 무엇(없으면 빈 구멍)."""
    sp = f'<span class="tf-sp">{px(what, size * .72)}</span>' if what else ""
    return (f'<span class="tf-plot {escape(cls)}" style="--s:{size}px">{sp}'
            f'<span class="tf-ground">{px("tile" if what else "hole", size)}</span></span>')


ART = {"spr": SPR, "col": COL}
