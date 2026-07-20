# -*- coding: utf-8 -*-
"""정비이력 전용 Apps Script **소스 + 배포 스크립트** (차량관리 앱 백엔드 2개 중 하나).

★ 이 파일이 배포본의 **유일한 소스**다 — 편집기에서 직접 고치지 말 것(버전관리 밖으로 새어나간다).
실행: py -X utf8 -m audit.deploy_maintenance_api   → 코드 업로드 → 새 버전 → 기존 배포 갱신

구조:
  · 차량·오일·검사   : 기존 웹앱 AKfycbzlrOLKx9…  ← 시트 bound 라 scriptId 를 알 수 없어 **못 고친다**
  · 정비이력·타이어  : 이 웹앱 AKfycbwtdykb6e2N…   ← 그래서 따로 띄웠다. _정비이력·_타이어 탭 담당.

⚠️ 배포 갱신은 **기존 deploymentId 를 PUT** 으로 할 것. 새 배포를 만들면 URL 이 바뀌어
   docs/index.html 의 MAINT_URL 도 같이 고쳐야 한다.
⚠️ API 로 만든 스크립트는 **소유자가 편집기에서 ▶실행 → 승인**을 한 번 해야 동작한다
   (Authorization needed). 대리 불가. 단 승인 후에는 scope 가 그대로면 재승인 없이 갱신된다.
⚠️ 시트 탭은 반드시 `_` 로 시작 — 기존 웹앱 getBranches() 가 `_` 없는 탭을 전부 지점으로 인식해
   앱 상단에 지점 탭처럼 튀어나온다.
"""
import json, pathlib, sys, urllib.error, urllib.parse, urllib.request
sys.stdout.reconfigure(encoding="utf-8")
SCRIPT_ID = "1iB29yFs0_6AxhHjT5dEl5ayNSfTuhYFkxW25h__SJv8bv_DisOjz9tGx"
DEPLOY_ID = "AKfycbwtdykb6e2NGRoP6pBJVCYoh2xP5uA3ZpOMoogUIAZ0hlCjP4P48-dvq4kAmGS1uwXqFw"
SHEET_ID = "1ErsNQ7elSORuB6Z20cKUOWjdroxp-4-01N0WoW6PAOI"

CODE = r"""
const SHEET_ID = '%s';
const MH_SHEET = '_정비이력';
// 첨부링크·첨부파일명 추가 — 앱에서 📎 를 눌러 드라이브 내역서를 연다(caring.co.kr 한정 공개)
const MH_HEADERS = ['지점','차량번호','차량명','정비일','구분','정비내역','부품','첨부','첨부링크','첨부파일명'];
const TIRE_SHEET = '_타이어';
const TIRE_HEADERS = ['지점','차량번호','차량명','타이어사이즈','근거정비일'];
const INS_SHEET = '_보험';
const INS_HEADERS = ['지점','차량번호','차량명','보험사','보험만기','증서파일명'];

function doGet(e)  { return handle(((e && e.parameter) || {}).action, (e && e.parameter) || {}); }
function doPost(e) {
  var b = {};
  try { b = JSON.parse((e && e.postData && e.postData.contents) || '{}'); }
  catch (err) { return json({ ok: false, error: 'invalid JSON' }); }
  return handle(b.action, b);
}
function handle(action, p) {
  try {
    var data;
    switch (action) {
      case 'getMaintenance':  data = getMaintenance(); break;
      case 'syncMaintenance': data = syncMaintenance(p.history, p.tires, p.insurance); break;
      case 'ping':            data = { pong: true }; break;
      default: return json({ ok: false, error: 'Unknown action: ' + action });
    }
    return json({ ok: true, data: data });
  } catch (err) { return json({ ok: false, error: String((err && err.message) || err) }); }
}
function json(o) {
  return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON);
}
function getMaintenance() {
  var ss = SpreadsheetApp.openById(SHEET_ID);
  function read(name) {
    var sh = ss.getSheetByName(name);
    if (!sh || sh.getLastRow() < 2) return [];
    return sh.getRange(2, 1, sh.getLastRow() - 1, sh.getLastColumn()).getValues();
  }
  function fmt(v) {
    if (v instanceof Date) return Utilities.formatDate(v, 'Asia/Seoul', 'yyyy-MM-dd');
    var s = String(v || '');
    if (!s) return '';
    var d = new Date(s);                     // 문자열 날짜(ISO·Date.toString)도 yyyy-MM-dd 로
    return isNaN(d.getTime()) ? s : Utilities.formatDate(d, 'Asia/Seoul', 'yyyy-MM-dd');
  }
  function lines(v) {
    var s = String(v || '').trim();
    return s ? s.split('\n').filter(function (x) { return x.trim(); }) : [];
  }
  var history = {};
  read(MH_SHEET).forEach(function (r) {
    var k = String(r[1] || '').trim();
    if (!k) return;
    var urls = lines(r[8]), names = lines(r[9]);
    (history[k] = history[k] || []).push({
      date: fmt(r[3]), type: String(r[4] || ''), desc: String(r[5] || ''),
      parts: String(r[6] || '') ? String(r[6]).split(',') : [],
      files: Number(r[7] || 0),
      atts: urls.map(function (u, i) { return { url: u, name: names[i] || ('첨부' + (i + 1)) }; })
    });
  });
  Object.keys(history).forEach(function (k) {
    history[k].sort(function (a, b) { return b.date.localeCompare(a.date); });
  });
  var tires = {};
  read(TIRE_SHEET).forEach(function (r) {
    var k = String(r[1] || '').trim();
    if (k && r[3]) tires[k] = { size: String(r[3]), date: fmt(r[4]) };
  });
  var insurance = {};
  read(INS_SHEET).forEach(function (r) {
    var k = String(r[1] || '').replace(/\s+/g, '');   // 앱 carKey(공백제거)와 맞춤 — '380마 4864' 같은 표기도 조인
    if (k && (r[3] || r[4])) insurance[k] = { insurer: String(r[3] || ''), expiry: fmt(r[4]), cert: String(r[5] || '') };
  });
  return { history: history, tires: tires, insurance: insurance };
}
function syncMaintenance(history, tires, insurance) {
  var ss = SpreadsheetApp.openById(SHEET_ID);
  function put(name, headers, rows) {
    var sh = ss.getSheetByName(name);
    if (!sh) sh = ss.insertSheet(name);
    sh.clear();
    sh.getRange(1, 1, 1, headers.length).setValues([headers]).setFontWeight('bold').setBackground('#e8eaf6');
    sh.setFrozenRows(1);
    if (rows && rows.length) sh.getRange(2, 1, rows.length, headers.length).setValues(rows);
    return rows ? rows.length : 0;
  }
  // 보낸 데이터의 탭만 갱신 — 보험만 sync 할 때 정비이력·타이어를 지우지 않도록(그 반대도)
  var out = { at: Utilities.formatDate(new Date(), 'Asia/Seoul', 'yyyy-MM-dd HH:mm') };
  if (history   != null) out.history   = put(MH_SHEET, MH_HEADERS, history);
  if (tires     != null) out.tires     = put(TIRE_SHEET, TIRE_HEADERS, tires);
  if (insurance != null) out.insurance = put(INS_SHEET, INS_HEADERS, insurance);
  return out;
}
""" % SHEET_ID

MANIFEST = {"timeZone": "Asia/Seoul", "exceptionLogging": "STACKDRIVER", "runtimeVersion": "V8",
            "oauthScopes": ["https://www.googleapis.com/auth/spreadsheets"],
            "webapp": {"executeAs": "USER_DEPLOYING", "access": "ANYONE_ANONYMOUS"}}

def token():
    d = json.loads((pathlib.Path.home() / ".clasprc.json").read_text())
    t = d.get("tokens", {}).get("default") or d.get("token") or {}
    body = urllib.parse.urlencode({
        "client_id": d.get("oauth2ClientSettings", {}).get("clientId") or t.get("client_id"),
        "client_secret": d.get("oauth2ClientSettings", {}).get("clientSecret") or t.get("client_secret"),
        "refresh_token": t.get("refresh_token"), "grant_type": "refresh_token"}).encode()
    return json.load(urllib.request.urlopen(
        urllib.request.Request("https://oauth2.googleapis.com/token", data=body)))["access_token"]

def api(at, url, data=None, method=None):
    r = urllib.request.Request(url, data=json.dumps(data).encode() if data is not None else None,
                               headers={"Authorization": "Bearer " + at, "Content-Type": "application/json"},
                               method=method)
    try: return json.load(urllib.request.urlopen(r))
    except urllib.error.HTTPError as e: return {"ERR": e.read().decode()[:300]}

at = token()
r = api(at, f"https://script.googleapis.com/v1/projects/{SCRIPT_ID}/content",
        {"files": [{"name": "appsscript", "type": "JSON", "source": json.dumps(MANIFEST, ensure_ascii=False)},
                   {"name": "Code", "type": "SERVER_JS", "source": CODE}]}, method="PUT")
print("코드 업로드:", "OK" if r.get("files") else r.get("ERR"))
v = api(at, f"https://script.googleapis.com/v1/projects/{SCRIPT_ID}/versions", {"description": "보험(_보험) 탭 추가"})
print("버전:", v.get("versionNumber") or v.get("ERR"))
# ★ 기존 배포를 새 버전으로 갱신 — 새 배포를 만들면 URL 이 바뀌어 앱을 또 고쳐야 한다
u = api(at, f"https://script.googleapis.com/v1/projects/{SCRIPT_ID}/deployments/{DEPLOY_ID}",
        {"deploymentConfig": {"versionNumber": v["versionNumber"], "manifestFileName": "appsscript",
                              "description": "정비이력 API"}}, method="PUT")
print("배포 갱신:", "OK" if u.get("deploymentId") else u.get("ERR"))
