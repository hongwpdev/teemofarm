"""티모의 버섯농장 — LoL 리그별 소식·로스터·이적 모음. 시작 파일.

외부 의존성 없음(파이썬 표준 라이브러리만 사용). 코드는 tracker/ 폴더에 나뉘어 있음:
  config.py   설정·리그·팀 목록      core.py     HTTP·DB·날짜 도우미
  classify.py 기사 성격·팀 판정       cargo.py    리그피디아 Cargo 조회
  wiki.py · news.py · fa.py  수집(편집 기록·뉴스·FA·로스터·프로필)
  jobs.py     수집 일정·[조회]        web/        화면(views.py)·서버(server.py)·static(css·js)

자동 재시작(기본 켜짐, RELOAD=0 이면 끔): 이 파일이 '감독' 역할만 하고 실제 서버는 자식 프로세스로 띄운다.
tracker/ 아래 코드·화면 파일이 바뀌면 서버를 알아서 다시 띄우고, 서버가 죽어도 5초 뒤 다시 띄운다.
그래서 코드를 고친 뒤 창에서 직접 끄고 켤 필요가 없다. 끌 때는 이 창에서 Ctrl+C 한 번.
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
WATCH_EXT = (".py", ".css", ".js", ".json")
CTRL_C_CODES = (-2, 3221225786, -1073741510)   # 리눅스 SIGINT, 윈도우 STATUS_CONTROL_C_EXIT


def signature():
    """감시 대상 파일들의 (경로, 수정 시각, 크기) 목록."""
    out = []
    for root, dirs, files in os.walk(os.path.join(HERE, "tracker")):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in files:
            if f.endswith(WATCH_EXT):
                p = os.path.join(root, f)
                try:
                    st = os.stat(p)
                    out.append((p, st.st_mtime, st.st_size))
                except OSError:
                    pass
    return sorted(out)


def say(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), "INFO [재시작 감독]", msg, flush=True)


def supervise():
    cmd = [sys.executable, "-c", "from tracker.web.server import main; main()"]
    while True:
        last = signature()
        child = subprocess.Popen(cmd, cwd=HERE)
        reason = ""
        try:
            while child.poll() is None:
                time.sleep(3)
                now = signature()
                if now != last:
                    time.sleep(2)            # 파일 여러 개가 연달아 바뀌는 중일 수 있어 잠깐 기다림
                    reason = "코드가 바뀌어 다시 띄웁니다"
                    break
            if not reason:
                if child.returncode in CTRL_C_CODES:   # Ctrl+C가 서버에 먼저 닿은 경우: 감독도 끝냄
                    say("Ctrl+C — 서버를 껐습니다")
                    return
                reason = f"서버가 멈춰서(종료 코드 {child.returncode}) 5초 뒤 다시 띄웁니다"
                say(reason)
                time.sleep(5)
                continue
            say(reason)
            child.terminate()
            try:
                child.wait(10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        except KeyboardInterrupt:
            say("Ctrl+C — 서버를 끕니다")
            child.terminate()
            try:
                child.wait(10)
            except subprocess.TimeoutExpired:
                child.kill()
            return


if __name__ == "__main__":
    if os.getenv("RELOAD", "1") == "0":
        from tracker.web.server import main
        main()
    else:
        supervise()
