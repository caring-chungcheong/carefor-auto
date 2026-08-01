# -*- coding: utf-8 -*-
"""주간보호 공유허브 배포 — Apps Script 웹앱(caring.co.kr 도메인 제한).

왜 별도 허브인가 (2026-08-01 회원님 확정):
  충청본부 공유 허브는 **본부 전용**이다. 거긴 매출 점검·본인부담금 미납·송영 코스처럼
  지점에 열면 안 되는 자료가 같이 들어 있고, Apps Script 웹앱은 **페이지별 권한이 없다**
  (doGet 이 ?page= 만 보고 파일을 내주고, 접근제어는 '도메인 계정인가' 하나뿐이다).
  → 지점에 본부 허브 주소를 주면 첫 화면으로 나가 나머지 자료도 전부 열 수 있다.
  그래서 **지점과 함께 보는 것만** 담은 허브를 따로 둔다(방문요양 허브와 같은 구조).

담는 것
  dashboard : 주간보호 대시보드  ← 클로드코드/주간보호대시보드/주간보호_대시보드.html
  calc      : 주야간 이용료 계산기 ← carefor-auto/docs/daycare_calculator.html

★함정
- doGet 의 map 에 없는 page 는 조용히 무시되고 첫 화면이 뜬다 — 페이지를 얹으면 반드시 추가.
- 끌어온 페이지에 '← 본부 공유 허브' 복귀 링크가 박혀 있으면 여기서 본부 허브로 튕겨 나간다
  → strip_hq_back 으로 걷어내고 이 허브의 복귀 바를 새로 붙인다.
- 접속 로깅은 충청본부 차량관리 시트의 `_주간보호허브접속` 탭에 쌓는다(시트를 늘리지 않는다).
  ★spreadsheets 권한은 doGet 승인으로 빠질 수 있다 — 편집기에서 setup() 을 한 번 실행해 승인할 것.
- SCRIPT_ID/DEPLOY_ID 를 잃으면 재배포가 **새 주소**를 만들어 지점 안내를 다시 해야 한다.

실행
  py -X utf8 -m audit.deploy_daycare_hub --create   # 최초 1회
  py -X utf8 -m audit.deploy_daycare_hub            # 갱신
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8")

from audit.deploy_homecare_hub import api, strip_hq_back, token  # noqa: E402  (같은 방식 재사용)

ROOT = pathlib.Path(__file__).resolve().parent.parent
CC = ROOT.parent                      # 클로드코드/
SHEET_ID = "1ErsNQ7elSORuB6Z20cKUOWjdroxp-4-01N0WoW6PAOI"   # 충청본부 차량관리 — 시트를 더 늘리지 않는다
LOG_SHEET = "_주간보호허브접속"

# ★배포 후 아래 두 값을 채워 넣을 것(비우면 매번 새 주소가 만들어진다).
SCRIPT_ID = "1Kml8AYhSc4yPPjDPsejG9vqNVrl_jxkZI2FHoSoaJmET3eeF5a21CuBO"
DEPLOY_ID = "AKfycbwEasrkyH1SAX-rWSbkT10-YvVamR75YcimO7H_lAfhJh1_chxt61nUhP1um2r9ZQ_p"

DASH_SRC = CC / "주간보호대시보드" / "주간보호_대시보드.html"
CALC_SRC = ROOT / "docs" / "daycare_calculator.html"

MANIFEST = {
    "timeZone": "Asia/Seoul", "exceptionLogging": "STACKDRIVER", "runtimeVersion": "V8",
    "oauthScopes": ["https://www.googleapis.com/auth/spreadsheets",
                    "https://www.googleapis.com/auth/userinfo.email"],
    # 🔒 caring.co.kr 계정만 열린다 — 이게 접근제어를 만들어 준다
    "webapp": {"executeAs": "USER_DEPLOYING", "access": "DOMAIN"},
}

CODE = r"""
const SHEET_ID  = '%s';
const LOG_SHEET = '%s';
const HEADERS   = ['시각', '이메일', '항목'];

/** ★최초 1회 편집기에서 이 함수를 골라 ▶실행 → 승인.
 *  doGet 으로 승인하면 spreadsheets 권한이 빠진 채 승인될 수 있다(충청본부 허브 실측). */
function setup() {
  sheet_().appendRow([new Date(), who_(), '설치 확인']);
  return LOG_SHEET + ' 탭 준비 완료';
}

function doGet(e) {
  var page = (e && e.parameter && e.parameter.page) || '';
  // ⚠️ 여기에 없는 page 는 조용히 무시되고 첫 화면이 뜬다 — 페이지를 얹으면 반드시 추가할 것.
  var map = { dashboard: '주간보호 대시보드', calc: '주야간 이용료 계산기' };
  if (map[page]) { return out_(page, map[page]); }
  return out_('hub', '주간보호 공유허브');
}
function out_(file, title) {
  return HtmlService.createHtmlOutputFromFile(file)
    .setTitle(title)
    .addMetaTag('viewport', 'width=device-width, initial-scale=1')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

function who_() {
  try { return Session.getActiveUser().getEmail() || '(알수없음)'; }
  catch (err) { return '(알수없음)'; }
}

function sheet_() {
  var ss = SpreadsheetApp.openById(SHEET_ID);
  var sh = ss.getSheetByName(LOG_SHEET);
  if (!sh) {
    sh = ss.insertSheet(LOG_SHEET);
    sh.getRange(1, 1, 1, HEADERS.length).setValues([HEADERS])
      .setFontWeight('bold').setBackground('#e8f0f1');
    sh.setFrozenRows(1);
  }
  return sh;
}

/** 로그 한 줄. 같은 사람의 같은 항목이 dedupeMin 안에 있으면 줄을 늘리지 않고 시각만 갱신한다. */
function log_(item, dedupeMin) {
  try {
    var sh = sheet_(), email = who_(), now = new Date(), last = sh.getLastRow();
    if (dedupeMin && last >= 2) {
      var prev = sh.getRange(last, 1, 1, 3).getValues()[0];
      var pd = prev[0] instanceof Date ? prev[0] : new Date(prev[0]);
      if (String(prev[1]) === email && String(prev[2]) === item &&
          (now - pd) < dedupeMin * 60000) {
        sh.getRange(last, 1).setValue(now);
        return;
      }
    }
    sh.appendRow([now, email, item]);
  } catch (err) { /* 로깅 실패가 허브를 막으면 안 된다 */ }
}

function logItem(item) { log_(String(item || '').slice(0, 60)); return true; }
""" % (SHEET_ID, LOG_SHEET)

BACKBAR = """
<style>@media print{.hubbar{display:none !important}}</style>
<div class="hubbar" style="position:sticky;top:0;z-index:9999;background:#0d7268;padding:9px 16px;
            font:600 13px/1 'Pretendard Variable',Pretendard,'Malgun Gothic',sans-serif;">
  <a href="%s" target="_top" style="color:#fff;text-decoration:none;">← 주간보호 허브</a>
</div>
"""


def page_html(src: pathlib.Path, hub_url: str) -> str:
    s = strip_hq_back(src.read_text(encoding="utf-8"))
    bar = BACKBAR % hub_url
    i = s.lower().find("<body")
    if i >= 0:
        j = s.find(">", i)
        return s[:j + 1] + bar + s[j + 1:]
    return bar + s


def hub_html(hub_url: str) -> str:
    return (ROOT / "apps_script" / "daycare_hub.html").read_text(
        encoding="utf-8").replace("__SELF__", hub_url)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--create", action="store_true", help="스크립트 프로젝트 새로 만들기(최초 1회)")
    args = ap.parse_args()

    for p in (DASH_SRC, CALC_SRC):
        if not p.exists():
            print(f"ERROR: 원본이 없습니다 — {p}")
            return 1

    at = token()
    sid, did = SCRIPT_ID, DEPLOY_ID

    if args.create or not sid:
        p = api(at, "https://script.googleapis.com/v1/projects", {"title": "주간보호 공유허브"})
        if p.get("ERR"):
            print("생성 실패:", p["ERR"])
            return 1
        sid = p["scriptId"]
        print("스크립트 생성:", sid)

    hub_url = f"https://script.google.com/a/macros/caring.co.kr/s/{did}/exec" if did else ""

    r = api(at, f"https://script.googleapis.com/v1/projects/{sid}/content", {"files": [
        {"name": "appsscript", "type": "JSON", "source": json.dumps(MANIFEST, ensure_ascii=False)},
        {"name": "Code", "type": "SERVER_JS", "source": CODE},
        {"name": "hub", "type": "HTML", "source": hub_html(hub_url)},
        {"name": "dashboard", "type": "HTML", "source": page_html(DASH_SRC, hub_url)},
        {"name": "calc", "type": "HTML", "source": page_html(CALC_SRC, hub_url)},
    ]}, method="PUT")
    print("코드 업로드:", "OK" if r.get("files") else r.get("ERR"))
    if r.get("ERR"):
        return 1

    v = api(at, f"https://script.googleapis.com/v1/projects/{sid}/versions",
            {"description": "주간보호 허브"})
    if v.get("ERR"):
        print("버전 실패:", v["ERR"])
        return 1
    print("버전:", v["versionNumber"])

    cfg = {"versionNumber": v["versionNumber"], "manifestFileName": "appsscript",
           "description": "주간보호 허브"}
    if did:
        u = api(at, f"https://script.googleapis.com/v1/projects/{sid}/deployments/{did}",
                {"deploymentConfig": cfg}, method="PUT")
    else:
        u = api(at, f"https://script.googleapis.com/v1/projects/{sid}/deployments", cfg)
        did = u.get("deploymentId")
    if u.get("ERR"):
        print("배포 실패:", u["ERR"])
        return 1

    url = f"https://script.google.com/a/macros/caring.co.kr/s/{did}/exec"
    print("\n배포 OK")
    print("  주소:", url)
    if (sid, did) != (SCRIPT_ID, DEPLOY_ID):
        print(f"\n⚠️ 이 파일 상단에 적어둘 것:\n  SCRIPT_ID = \"{sid}\"\n  DEPLOY_ID = \"{did}\"")
        print("  (다음 배포부터 같은 주소를 유지하려면 반드시 필요)")
    print("\n최초 1회: 위 주소를 브라우저에서 열어 caring.co.kr 계정으로 승인해야 합니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
