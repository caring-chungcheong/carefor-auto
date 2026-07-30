# -*- coding: utf-8 -*-
"""방문요양 공유허브 배포 — Apps Script 웹앱(caring.co.kr 도메인 제한).

왜 별도 허브인가: 근무일정표에 직원 실명이 들어 있는데 GitHub Pages 는
**접근제어가 안 된다**(Pages access control 은 Enterprise Cloud 전용).
그래서 공개 Pages 대신 도메인 로그인이 걸린 Apps Script 로 서빙한다.

담는 것
  schedule : 근무일정표   ← work-schedule/index.html 을 그대로 넣는다
  ratecalc : 수가계산기   ← carefor-auto/docs/rate_calculator.html
  drivelog : 운행기록     ← carefor-auto/docs/daejeon.html (시트 연동 입력 페이지)
  promo    : 홍보 리포트  ← 클로드코드/지점홍보리포트/대전방문요양.html (저장소 밖·공개금지)

★함정
- 접속 로깅은 충청본부 차량관리 시트의 _방문요양허브접속 탭에 쌓는다(시트를 늘리지 않는다).
  ★spreadsheets 권한은 doGet 승인으로 빠질 수 있다 — 화면에 '기록 없음'이 계속 뜨면
    편집기에서 setup() 을 한 번 실행해 승인해야 한다(log_/status 가 예외를 삼켜 조용히 실패).
- doGet 의 map 에 없는 page 는 조용히 무시되고 첫 화면이 뜬다 — 페이지를 얹으면 반드시 추가.
- 근무일정표는 localStorage 에 월별 편성을 저장한다. Apps Script 는 사용자 HTML 을
  googleusercontent 샌드박스 iframe 에서 띄우므로, **구글이 그 origin 을 바꾸면
  저장분이 초기화될 수 있다**. 영구 보관이 필요하면 앱의 '구글시트로 내보내기'를 쓸 것.

실행
  py -X utf8 -m audit.deploy_homecare_hub --create   # 최초 1회
  py -X utf8 -m audit.deploy_homecare_hub            # 갱신
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

ROOT = pathlib.Path(__file__).resolve().parent.parent
CC = ROOT.parent                      # 클로드코드/
SCHEDULE_SRC = pathlib.Path.home() / "work-schedule" / "index.html"
RATECALC_SRC = ROOT / "docs" / "rate_calculator.html"
DRIVELOG_SRC = ROOT / "docs" / "daejeon.html"        # 방문요양 대전점 운행기록
# 홍보 리포트는 경쟁센터 연락처 103건이 들어 있어 공개 Pages 금지 — 저장소 밖에 둔다.
PROMO_SRC    = CC / "지점홍보리포트" / "대전방문요양.html"

# ★ID 를 코드에 박아둔다 — 잃으면 재배포가 새 주소를 만들어 안내를 다시 해야 하고 승인도 다시 받는다.
#   비밀값 아님(주소는 어차피 직원에게 공유한다).
SCRIPT_ID = "1QRSMk6wl3ZVzG9BhqU7BzB2MCS8o62K-Bn2arQ3_wZOEG3J6Te3rW0dq"
DEPLOY_ID = "AKfycbyYBYMgBqAQMmVyNb4cD-LxB_bHZQnDAuigcU6yYvpx5vVQN3sCLFOmRVFNeNvOgZ_hhA"

SHEET_ID = "1ErsNQ7elSORuB6Z20cKUOWjdroxp-4-01N0WoW6PAOI"   # 충청본부 차량관리 — 시트를 더 늘리지 않는다
LOG_SHEET = "_방문요양허브접속"

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
 *  doGet 을 열어 승인하면 **시트 권한이 빠진 채로 승인될 수 있다**(충청본부 허브 실측:
 *  userinfo.email 만 승인되고 spreadsheets 가 빠져 로그가 조용히 실패했다).
 *  이 함수는 시트를 직접 건드리므로 구글이 spreadsheets 권한을 반드시 묻는다. */
function setup() {
  sheet_().appendRow([new Date(), who_(), '설치 확인']);
  return LOG_SHEET + ' 탭 준비 완료';
}

function doGet(e) {
  var page = (e && e.parameter && e.parameter.page) || '';
  // ⚠️ 여기에 없는 page 는 무시되고 첫 화면이 뜬다 — 페이지를 새로 얹으면 반드시 추가할 것.
  var map = { schedule: '근무일정표', ratecalc: '수가계산기',
              drivelog: '방문요양 대전점 운행기록', promo: '대전 방문요양 홍보 리포트' };
  if (map[page]) { return out_(page, map[page]); }
  // ★허브 열기 로깅은 doGet 이 아니라 status() 에서 한다 — 여기서 시트를 만지면
  //   시트 열기·쓰기(0.5~1.5초)가 끝나야 화면이 떠서 '멈춘 것처럼' 보인다.
  return out_('hub', '방문요양 공유허브');
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

function log_(item) {
  try { sheet_().appendRow([new Date(), who_(), item]); }
  catch (err) { /* 로깅 실패가 허브를 막으면 안 된다 */ }
}

/** 카드 클릭 — 화면에서 google.script.run 으로 부른다 */
function logItem(item) { log_(String(item || '').slice(0, 60)); return true; }

/** 상단 바에 뿌릴 현황: 나 · 최근 접속 20건 */
function status() {
  log_('허브 열기');
  var out = { me: who_(), recent: [] };
  try {
    var sh = sheet_(), last = sh.getLastRow();
    if (last < 2) return out;
    var n = Math.min(20, last - 1);
    var rows = sh.getRange(last - n + 1, 1, n, 3).getValues();
    out.recent = rows.reverse().map(function (r) {
      var d = r[0] instanceof Date ? r[0] : new Date(r[0]);
      return { t: Utilities.formatDate(d, 'Asia/Seoul', 'MM/dd HH:mm'),
               who: String(r[1]).split('@')[0], item: String(r[2]) };
    });
  } catch (err) {}
  return out;
}
""" % (SHEET_ID, LOG_SHEET)

# 개별 페이지 상단에 '허브로' 버튼을 끼워 넣는다(뒤로가기가 iframe 안에서 안 먹는 경우가 있어서)
BACKBAR = """
<div style="position:sticky;top:0;z-index:9999;background:#2f5c64;padding:9px 16px;
            font:600 13px/1 'Pretendard Variable',Pretendard,'Malgun Gothic',sans-serif;">
  <a href="%s" target="_top" style="color:#fff;text-decoration:none;">← 방문요양 공유허브</a>
</div>
"""


def token() -> str:
    d = json.loads((pathlib.Path.home() / ".clasprc.json").read_text(encoding="utf-8"))
    t = d.get("tokens", {}).get("default") or d.get("token") or {}
    body = urllib.parse.urlencode({
        "client_id": d.get("oauth2ClientSettings", {}).get("clientId") or t.get("client_id"),
        "client_secret": d.get("oauth2ClientSettings", {}).get("clientSecret") or t.get("client_secret"),
        "refresh_token": t.get("refresh_token"), "grant_type": "refresh_token"}).encode()
    return json.load(urllib.request.urlopen(
        urllib.request.Request("https://oauth2.googleapis.com/token", data=body)))["access_token"]


def api(at: str, url: str, data=None, method=None):
    r = urllib.request.Request(url, data=json.dumps(data).encode() if data is not None else None,
                               headers={"Authorization": "Bearer " + at,
                                        "Content-Type": "application/json"}, method=method)
    try:
        return json.load(urllib.request.urlopen(r))
    except urllib.error.HTTPError as e:
        return {"ERR": e.read().decode()[:400]}


def page_html(src: pathlib.Path, hub_url: str) -> str:
    s = src.read_text(encoding="utf-8")
    bar = BACKBAR % hub_url
    # <body> 바로 뒤에 넣는다. 못 찾으면 맨 앞에 붙여도 브라우저가 알아서 body 로 넣는다.
    i = s.lower().find("<body")
    if i >= 0:
        j = s.find(">", i)
        return s[:j + 1] + bar + s[j + 1:]
    return bar + s


def hub_html(hub_url: str) -> str:
    return (ROOT / "apps_script" / "homecare_hub.html").read_text(encoding="utf-8").replace("__SELF__", hub_url)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--create", action="store_true", help="스크립트 프로젝트 새로 만들기(최초 1회)")
    args = ap.parse_args()

    for p in (SCHEDULE_SRC, RATECALC_SRC, DRIVELOG_SRC, PROMO_SRC):
        if not p.exists():
            print(f"ERROR: 원본이 없습니다 — {p}"); return 1

    at = token()
    sid, did = SCRIPT_ID, DEPLOY_ID

    if args.create or not sid:
        p = api(at, "https://script.googleapis.com/v1/projects", {"title": "방문요양 공유허브"})
        if p.get("ERR"):
            print("생성 실패:", p["ERR"]); return 1
        sid = p["scriptId"]
        print("스크립트 생성:", sid)

    hub_url = f"https://script.google.com/a/macros/caring.co.kr/s/{did}/exec" if did else ""

    r = api(at, f"https://script.googleapis.com/v1/projects/{sid}/content", {"files": [
        {"name": "appsscript", "type": "JSON", "source": json.dumps(MANIFEST, ensure_ascii=False)},
        {"name": "Code", "type": "SERVER_JS", "source": CODE},
        {"name": "hub", "type": "HTML", "source": hub_html(hub_url)},
        {"name": "schedule", "type": "HTML", "source": page_html(SCHEDULE_SRC, hub_url)},
        {"name": "ratecalc", "type": "HTML", "source": page_html(RATECALC_SRC, hub_url)},
        {"name": "drivelog", "type": "HTML", "source": page_html(DRIVELOG_SRC, hub_url)},
        {"name": "promo", "type": "HTML", "source": page_html(PROMO_SRC, hub_url)},
    ]}, method="PUT")
    print("코드 업로드:", "OK" if r.get("files") else r.get("ERR"))
    if r.get("ERR"):
        return 1

    v = api(at, f"https://script.googleapis.com/v1/projects/{sid}/versions", {"description": "방문요양 허브"})
    if v.get("ERR"):
        print("버전 실패:", v["ERR"]); return 1
    print("버전:", v["versionNumber"])

    cfg = {"versionNumber": v["versionNumber"], "manifestFileName": "appsscript", "description": "방문요양 허브"}
    if did:
        u = api(at, f"https://script.googleapis.com/v1/projects/{sid}/deployments/{did}",
                {"deploymentConfig": cfg}, method="PUT")
    else:
        u = api(at, f"https://script.googleapis.com/v1/projects/{sid}/deployments", cfg)
        did = u.get("deploymentId")
    if u.get("ERR"):
        print("배포 실패:", u["ERR"]); return 1

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
