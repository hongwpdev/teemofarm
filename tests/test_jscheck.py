"""자바스크립트 실수 검사(파이썬만으로): 같은 범위에 같은 이름의 function이 두 번 있으면 뒤의 것이 앞의 것을 조용히 덮어씀.
예) schedule.js에서 팀 탭 거르기 show(t)와 경기 팝업 show()가 겹쳐, 팀 탭을 누르면 빈 팝업이 떴음."""
import os
import re
import unittest

STATIC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tracker", "web", "static")


def _strip(src: str) -> str:
    """문자열·주석·정규식 안의 글자는 공백으로 바꿔서 괄호 세기를 방해하지 않게(줄·위치는 그대로)."""
    out, i, n = [], 0, len(src)
    prev = ""                                   # 정규식(/…/)인지 나눗셈인지 판단용: 바로 앞의 의미 있는 글자
    while i < n:
        c = src[i]
        if src.startswith("//", i):
            j = src.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i)); i = j; continue
        if src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append(re.sub(r"[^\n]", " ", src[i:j])); i = j; continue
        if c in "'\"`":
            j = i + 1
            while j < n and src[j] != c:
                j += 2 if src[j] == "\\" else 1
            out.append(c + re.sub(r"[^\n]", " ", src[i + 1:j]) + c); i = j + 1; prev = c; continue
        if c == "/" and (prev == "" or prev in "(,=:[!&|?{};+-*%<>~^"):
            j, cls = i + 1, False
            while j < n and (src[j] != "/" or cls) and src[j] != "\n":
                if src[j] == "\\":
                    j += 1
                elif src[j] == "[":
                    cls = True
                elif src[j] == "]":
                    cls = False
                j += 1
            out.append("/" + " " * (j - i - 1) + "/"); i = j + 1; prev = "/"; continue
        out.append(c)
        if not c.isspace():
            prev = c
        i += 1
    return "".join(out)


def duplicate_functions(src: str):
    """[(이름, 첫 줄, 두 번째 줄)] — 같은 중괄호 범위 안에서 function 선언이 겹치는 것."""
    s = _strip(src)
    stack, seen, dups = [0], {0: {}}, []
    ids = 0
    for m in re.finditer(r"[{}]|\bfunction\s+([A-Za-z_$][\w$]*)\s*\(", s):
        tok = m.group(0)
        line = s.count("\n", 0, m.start()) + 1
        if tok == "{":
            ids += 1
            stack.append(ids)
            seen[ids] = {}
        elif tok == "}":
            if len(stack) > 1:
                stack.pop()
        else:
            name, scope = m.group(1), stack[-1]
            if name in seen[scope]:
                dups.append((name, seen[scope][name], line))
            else:
                seen[scope][name] = line
    return dups


class JsCheckTest(unittest.TestCase):
    def test_detects_shadowing(self):
        bad = "(function(){ function show(t){ return t } a.onclick=()=>show(1); function show(){ x() } })();"
        self.assertEqual([d[0] for d in duplicate_functions(bad)], ["show"])
        ok = "(function(){ function show(){} })(); (function(){ function show(){} })(); const s = 'function show(){}';"
        self.assertEqual(duplicate_functions(ok), [])

    def test_static_files(self):
        found = []
        for f in sorted(os.listdir(STATIC)):
            if f.endswith(".js"):
                with open(os.path.join(STATIC, f), encoding="utf-8") as fh:
                    found += [f"{f}: function {n} (줄 {a}, 줄 {b})" for n, a, b in duplicate_functions(fh.read())]
        self.assertEqual(found, [], "같은 범위에 같은 이름의 함수가 두 번 있어요(뒤의 것이 앞의 것을 덮어씀)")


if __name__ == "__main__":
    unittest.main()
