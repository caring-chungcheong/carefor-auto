# -*- coding: utf-8 -*-
"""수기 점수표 — 지점점검 대시보드와 **같은 페이지**에서 자동 판정만 끈 판.

왜 복제가 아니라 변환인가: 화면을 따로 만들면 항목·배점·조작법이 곧 갈린다.
`audit_dashboard.html` 을 그대로 쓰고 **자동 판정 데이터(AUDIT_DATA)만 비운다**.
항목 정의(AUDIT_ITEMS)는 그대로 두므로 36항목·배점·판정기준은 대시보드와 늘 같다.

결과: 모든 세부항목이 '미판정'으로 떠서 사람이 직접 점수를 넣는다.
      엑셀·PDF 내보내기, 메모, 지점별 저장은 대시보드 기능을 그대로 쓴다.
★수기 점수 저장 키가 대시보드와 같으면 서로 덮어쓴다 → localStorage 접두사를 갈라둔다.

실행: py -X utf8 -m audit.build_manual_score
결과: docs/manual_score.html  (공유허브 ?page=manualscore · 관제탑)
"""
from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "audit_dashboard.html"
OUT = ROOT / "docs" / "manual_score.html"

# 원본 로더: audit_results/dashboard_data.js (실명 포함, 로컬 전용)
# 수기표는 docs/ 에 두고 **같은 폴더의 마스킹본**을 읽는다. 어차피 DATA 는 비우므로
# 여기서 쓰는 건 AUDIT_ITEMS(항목 정의)뿐이다.
_LOADER = re.compile(r"document\.write\('<sc'\+'ript src=\"audit_results/dashboard_data\.js.*?</script>",
                     re.S)

ITEMS_SRC = ROOT / "docs" / "dashboard_data.js"


def _items_js() -> str:
    """docs/dashboard_data.js 에서 **항목 정의만** 떼어 온다(지점별 판정·명단은 안 가져온다).

    ★외부 파일로 두면 안 된다 — 허브(Apps Script)는 HTML 파일만 서빙해서
      `<script src="dashboard_data.js">` 가 404 로 죽는다(실측: 허브에서 화면이 깨졌다).
      그래서 항목 정의를 페이지 안에 박아 넣는다. 개인정보는 항목 정의에 없다.
    """
    s = ITEMS_SRC.read_text(encoding="utf-8")
    i = s.find("window.AUDIT_ITEMS")
    if i < 0:
        raise SystemExit(f"AUDIT_ITEMS 를 못 찾았습니다 — {ITEMS_SRC}. 먼저 run_audit 를 돌리세요.")
    body = s[i:].strip()
    if "AUDIT_DATA" in body:                     # 지점 데이터가 섞여 들어오면 자동판정이 살아난다
        raise SystemExit("AUDIT_ITEMS 뒤에 지점 데이터가 붙어 있습니다 — 중단.")
    return body


def build() -> str:
    s = SRC.read_text(encoding="utf-8")

    new_loader = ("</script>\n"
                  "<!-- ★수기 점수표: 항목 정의는 페이지에 박아 넣고(허브는 외부 .js 를 못 준다),\n"
                  "     자동 판정 데이터(AUDIT_DATA)는 비운다. -->\n"
                  "<script>\n" + _items_js() + "\nwindow.AUDIT_DATA = {};\n</script>")
    s, n = _LOADER.subn(lambda _m: new_loader, s, count=1)
    if n != 1:
        raise SystemExit("데이터 로더를 못 찾았습니다 — audit_dashboard.html 구조가 바뀐 듯합니다. "
                         "확인 없이 만들면 자동 판정이 섞여 들어갑니다.")

    # 엑셀 라이브러리 — 허브(Apps Script)는 vendor/*.js 를 서빙하지 못해 404 로 죽는다
    # (실측: '엑셀 내보내기'가 라이브러리 없음 경고만 내고 끝났다). CDN 으로 바꾼다.
    if 'src="vendor/xlsx.full.min.js"' not in s:
        raise SystemExit("xlsx 로더를 못 찾았습니다 — 엑셀 내보내기가 허브에서 죽습니다. 중단.")
    s = s.replace('src="vendor/xlsx.full.min.js"',
                  'src="https://cdn.jsdelivr.net/npm/xlsx@0.18.5/dist/xlsx.full.min.js"')

    # 제목 — 대시보드와 헷갈리지 않게
    s = re.sub(r"<title>[^<]*</title>", "<title>지점점검 대시보드(수기점검표)</title>", s, count=1)
    # 화면 안 제목도 바꾼다 — 안 바꾸면 대시보드와 똑같이 보여 어느 화면인지 헷갈린다
    s = s.replace("지점관리 점검 대시보드", "지점점검 대시보드(수기점검표)")

    # 수기 저장 키 분리 — 대시보드와 같은 키를 쓰면 서로 덮어쓴다(실측으로 확인).
    # ★키 이름이 바뀌면 조용히 공유 상태로 돌아가므로, 못 바꾸면 만들지 않는다.
    if s.count("'audit_manual_'") != 1:
        raise SystemExit("localStorage 키(manualKey)를 못 찾았습니다 — 대시보드와 점수가 섞입니다. 중단.")
    s = s.replace("'audit_manual_'", "'audit_manualonly_'")

    # ★본부 공유 점수 자동 내려받기 차단.
    #   대시보드는 열기만 해도 SCORES_HOOK 에서 남이 매긴 점수를 받아 칸을 채운다(실측: 46칸·55.05점).
    #   수기표는 '백지에서 직접 매기는' 화면이라 이게 들어오면 목적이 무너진다.
    #   업로드(postScores)도 같이 막는다 — 백지 점수가 본부 값을 덮어쓰면 안 된다.
    hook = re.search(r"(const|var)\s+SCORES_HOOK\s*=\s*['\"][^'\"]*['\"]", s)
    if not hook:
        raise SystemExit("SCORES_HOOK 을 못 찾았습니다 — 본부 점수가 수기표에 섞입니다. 중단.")
    s = s[:hook.start()] + f"{hook.group(1)} SCORES_HOOK = ''" + s[hook.end():]

    # 화면에 '수기 전용'임을 밝힌다(자동 수집 시각이 비어 보이는 이유)
    banner = ("""<div style="background:#fff4e5;border:1px solid #f0c992;border-radius:8px;
padding:9px 12px;font-size:13px;color:#7a4a00;margin:10px 0">
✍️ <b>수기 전용</b> — 자동 판정을 끈 화면입니다. 모든 항목이 '미판정'으로 떠 있으니 직접 점수를 넣으세요.
항목·배점·판정기준은 지점점검 대시보드와 같습니다. 점수는 대시보드와 <b>따로</b> 저장됩니다.
</div>""")
    m = re.search(r"<body[^>]*>", s)
    if m:
        s = s[:m.end()] + banner + s[m.end():]

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    return s.replace("</html>", f"<!-- 생성: build_manual_score.py {stamp} -->\n</html>")


def main() -> int:
    OUT.write_text(build(), encoding="utf-8")
    print("생성:", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
