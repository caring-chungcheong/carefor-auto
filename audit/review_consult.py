# -*- coding: utf-8 -*-
"""상담일지 내용 검수 — 전문 발췌 + 인정/불인정 자동 1차판정 + 조치사항.

판정 규칙 (사용자 확정 2026-07-24):
  ① 일방향 안내(센터→보호자 통보만, 보호자 발화·의견 없음)는 상담 불인정
     예: "법인 변경으로 식비 10% 인상 안내드리고 문의사항 있으시면 연락달라고 말씀드림"
  ② 단순 비용 안내(본인부담금 초과금 발생 안내 등)는 불인정
  ③ 간호사가 상담한 건은 불인정
  ④ 퇴소처리 진행 상담은 예외 — 이 건을 빼고 그 분기에 상담이 한 건 더 있어야 함
  ⑤ 상담내용 아래 '조치내용'이 있어야 함(공란이면 보완)
  + 평가기준상 상담방법은 내방·방문·전화만 인정(문자·SNS 일방향 불인정)

자동판정은 1차 스크리닝이다. 애매한 건은 '확인필요'로 두고 전문을 그대로 실어
사람이 최종 판단하도록 한다(과탐으로 지점에 잘못된 수정지시가 나가는 것을 막기 위함).

사용:
  py -X utf8 -m audit.review_consult 둔산
입력: 평가준비/<지점>/상담일지_전문_<지점>.json  (audit.collect_consult_full 산출)
출력: 같은 폴더에 상담일지_검수_<지점>.html / .json
"""
from __future__ import annotations

import argparse
import difflib
import html
import json
import re
import sys
from collections import defaultdict, Counter

sys.stdout.reconfigure(encoding="utf-8")

from pathlib import Path

from .deskpath import out_dir

_RES = Path(__file__).resolve().parent.parent / "audit_results"


def _grade_out_periods(branch_label: str) -> dict:
    """audit_results/level_history_<지점>.json → {이름: [(start8, end8, 등급외여부)]}.
    등급외 기간엔 급여 수급자가 아니라 분기별 상담 의무가 없다 → gaps 계산에서 그 분기 제외.
    파일 없으면 {} (기존 동작 유지, 제외 안 함)."""
    f = _RES / f"level_history_{branch_label}.json"
    if not f.exists():
        return {}
    try:
        lh = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out: dict[str, list] = {}
    for r in lh.get("people", []):
        segs = []
        for g in r.get("grades", []):
            s = (g.get("start") or "").replace(".", "")
            e = (g.get("end") or "").replace(".", "")
            if len(s) == 8 and len(e) == 8:
                segs.append((s, e, "등급외" in (g.get("grade") or "")))
        out[r.get("name")] = segs
    return out

# ── 신호 사전 ────────────────────────────────────────────────────────────────
# 보호자·수급자 쪽 발화(쌍방향 근거). '문의사항 있으시면'처럼 센터 발화인 표현은 제외해야 하므로
# 주체가 보호자/어르신으로 특정되는 형태를 우선한다.
VOICE_RE = re.compile(
    r"(보호자|어르신|수급자|따님|아드님|자녀|배우자|가족|본인)[^.\n]{0,60}"
    r"(요청|요구|희망|원하|말씀|의견|불편|호소|건의|부탁|당부|질문|여쭈|상의|협의|궁금|"
    r"이야기|밝힘|답변|알려주|전달해 주|동의|거절|사양|미루|보류|하시겠다|주시기로|하기로)"
)
# 주체가 생략된 축약형 보조 신호 (지점 상담일지 실제 표기 기준)
VOICE_WEAK_RE = re.compile(
    r"(요청\s*하[심셨서]|요청함|희망\s*하[심셨]|희망함|원하[심셨]|말씀\s*주심|말씀\s*하[심셨]|"
    r"부탁\s*하[심셨]|당부\s*하[심셨]|궁금해하[심셨]|호소[함하]|거부하[심셨]|동의\s*하[심셨]|"
    r"전달\s?받|여쭤\s*보[심셨]|기로\s*하[심셨]|기로\s*함|하시겠다고|주시기로|의사를 밝힘|"
    r"[다요]고\s*하[심셨]|하신다고|하겠다고|속상해하[심셨])")

# 사용자가 지목한 전형적 일방향 통보 문형(이건 확정 불인정)
STRONG_ONEWAY_RE = re.compile(r"(문의사항\s*있으시면|편하게 연락|언제든지.{0,10}연락|양해\s*부탁|"
                              r"협조\s*부탁드림|안내만 드림|공지드림)")

# 센터→보호자 일방향 통보 신호
ONEWAY_RE = re.compile(
    r"(안내드림|안내함|안내드리고|안내드렸|공지|통보|연락드림|설명드림|설명함|전달드림|전달함|"
    r"문의사항 있으시면|편하게 연락|양해 부탁|협조 부탁)"
)
# 단순 비용 안내. '카드·계좌·비용' 같은 범용어를 넣으면 스팸전화 대응 상담까지 걸린다(과탐 확인 2026-07-24).
COST_RE = re.compile(r"(본인부담금|초과금|이용료|식비|미납|수납|납부|청구서?)")
# 퇴소처리 진행
OUT_RE = re.compile(r"(퇴소처리|퇴소 처리|퇴소하[심시게]|퇴소함|퇴소 요청|퇴소요청|퇴소 진행|계약 종료|계약종료)")
# 인정 방법(평가기준: 내방·방문·전화)
WAY_OK = ("전화통화", "대면상담", "방문상담", "내방상담")

VERDICT_ORDER = {"불인정": 0, "확인필요": 1, "제외(퇴소)": 2, "인정": 3}


def _q(yyyymmdd: str) -> tuple:
    y, m = int(yyyymmdd[:4]), int(yyyymmdd[4:6])
    return y, (m - 1) // 3 + 1


def clean(t: str) -> str:
    """DB에 이중 이스케이프된 &lt;...&gt; 복원 + 개행 정리."""
    t = (t or "").replace("\r\n", "\n").replace("\r", "\n")
    if "&lt;" in t or "&gt;" in t or "&amp;" in t:
        t = html.unescape(t)
    t = t.replace("\u200E", "").replace("​", "")
    return "\n".join(ln.rstrip() for ln in t.split("\n")).strip()


def judge(rec: dict, job: str | None) -> dict:
    """상담 1건 → {verdict, reasons[], fixes[]}."""
    body = clean(rec.get("pascctt"))
    act = clean(rec.get("pasactt"))
    gubun = clean(rec.get("pasgbct"))
    way = (rec.get("pascway") or "").strip()
    hay = f"{gubun}\n{body}"

    reasons, fixes = [], []
    verdict = "인정"

    # ④ 퇴소처리 — 예외(이 건은 분기 상담 실적에서 빼고 별도 1건 필요)
    if OUT_RE.search(hay) and len(body) < 400:
        return {"verdict": "제외(퇴소)", "reasons": ["퇴소처리 진행 상담 — 분기 실적에서 제외"],
                "fixes": ["이 건을 뺀 해당 분기 상담이 한 건 더 있어야 함"], "body": body, "act": act}

    # 쌍방향 근거는 상담내용뿐 아니라 조치내용에도 적힌다("여벌옷 보내주시기로 하셨음" 등).
    # 둘을 합쳐 봐야 일방향 과탐이 안 난다(2026-07-24 표본 대조로 확인).
    both = f"{body}\n{act}"
    voice = bool(VOICE_RE.search(both)) or bool(VOICE_WEAK_RE.search(both))
    oneway = bool(ONEWAY_RE.search(body))

    # ② 단순 비용 안내 — 비용이 '상담 주제'일 때만(구분란 또는 도입부). 본문 중간에 스쳐 나온 건 제외.
    cost_topic = bool(COST_RE.search(gubun)) or bool(COST_RE.search(body[:120]))
    other_topic = re.search(r"(만족|건강\s?상태|프로그램|낙상|투약|복약|목욕|기저귀|병원|진료|"
                            r"인지|재활|욕구|식사\s?형태|보행|건의)", hay)
    if cost_topic and not other_topic:
        verdict = "불인정"
        reasons.append("단순 비용(본인부담금·이용료) 안내 — 상담 불인정")
        fixes.append("비용 안내는 상담일지 실적에서 제외. 해당 분기 별도 상담 필요")
    # ① 일방향 안내 — 전형 문형('문의 있으시면 연락달라')만 확정 불인정, 나머지는 확인필요.
    #    조치내용에만 보호자 반응이 적힌 건이 많아 단정하면 과탐이 난다(표본 대조 2026-07-24).
    elif oneway and not voice:
        if STRONG_ONEWAY_RE.search(body):
            verdict = "불인정"
            reasons.append("일방향 안내 — 센터 통보 + '문의 시 연락' 마무리, 보호자 발화 없음")
        else:
            verdict = "확인필요"
            reasons.append("일방향 소지 — 센터 안내만 기술되고 보호자 발화·의견이 안 보임")
        fixes.append("보호자 발화(요청·의견·동의 사유)→센터 응답→반영 결과의 대화체로 재작성")
    elif not voice:
        verdict = "확인필요"
        reasons.append("보호자·수급자 발화가 명확히 드러나지 않음")
        fixes.append("보호자 의견·요구를 직접 인용해 보완")

    # ③ 간호사 상담 — 정식 간호사는 불인정, 간호조무사는 확인필요로만(사용자 확정 2026-07-25).
    if job and job == "간호사":
        if verdict not in ("불인정",):
            verdict = "불인정"
        reasons.append(f"상담직원 {rec.get('stmname')} = 간호사 — 간호사 상담은 불인정")
        fixes.append("사회복지사·시설장 등 상담 자격자 명의로 재작성(또는 별도 상담 실시)")
    elif job and "간호조무" in job:
        if verdict == "인정":
            verdict = "확인필요"
        reasons.append(f"상담직원 {rec.get('stmname')} = 간호조무사 — 상담 자격 확인 필요")
        fixes.append("간호조무사 상담 인정 여부 확인(불인정 시 자격자 명의로 재작성)")

    # 상담방법
    if way not in WAY_OK:
        if verdict == "인정":
            verdict = "확인필요"
        reasons.append(f"상담방법 '{way or '미기재'}' — 평가는 내방·방문·전화만 인정")
        fixes.append("전화·대면 상담으로 실시하고 방법 정정")

    # ⑤ 조치내용
    if not act:
        if verdict == "인정":
            verdict = "확인필요"
        reasons.append("조치내용 공란")
        fixes.append("상담내용 아래 조치내용(반영·후속조치) 작성")

    # 기재사항
    if not (rec.get("pasobjt") or "").strip():
        reasons.append("상담대상자명 미기재")
        fixes.append("상담대상자명(관계) 기재 — 2026.1월부터 필수")
    if not (rec.get("stmname") or "").strip():
        reasons.append("상담직원명 미기재")
        fixes.append("상담직원명 기재 — 2026.1월부터 필수")

    return {"verdict": verdict, "reasons": reasons, "fixes": fixes, "body": body, "act": act}


def build(key: str) -> dict:
    src = out_dir(key) / f"상담일지_전문_{key}.json"
    d = json.loads(src.read_text(encoding="utf-8"))
    jobs = d.get("staff_jobs") or {}
    by_person = defaultdict(list)
    for rec in d["consults"]:
        r = dict(rec)
        r.update(judge(rec, jobs.get((rec.get("stmname") or "").strip())))
        by_person[rec["pamname"]].append(r)
    for v in by_person.values():
        v.sort(key=lambda x: x["pasdate"])

    # 중복 작성 검사 — 같은 수급자의 상담내용(공백 제거)이 앞선 건과 동일하면 두 번째부터 '중복 소지'.
    # 복사·붙여넣기로 분기 실적을 채운 건을 잡는다(사용자 요청 2026-07-29). 첫 건은 유지,
    # 복제본이 '인정'이면 '확인필요'로 내려 그 분기가 중복만으로 충족되지 않게 한다(사람이 최종판단).
    # ★완전 일치만 보면 놓친다 — 날짜·이름 한 글자만 바꿔도 빠져나간다.
    #   실제로 한 수급자 안에 복붙 4건이 있는데 0건으로 나온 사례가 있었다(회원님 지적 2026-08-04).
    #   → ①공백·숫자·문장부호를 지운 '느슨한 키' 일치 ②유사도 85% 이상 둘 다 잡는다.
    def _loose(s: str) -> str:
        return re.sub(r"[\s\d.,·/()\[\]~\-:;!?'\"]+", "", s or "")

    # ★상담내용(body)만 보면 놓친다 — 실제 청주 복붙은 **조치내용(act)** 에 몰려 있었다
    #   (실측 2026-08-04: 조치내용 100% 동일 1건, 같은 문구를 18명에게 사용).
    #   또 상담내용 복붙은 75~83% 구간에 몰려서 85% 기준으로는 전부 빠져나갔다.
    #   → 두 칸 다 보고 임계값을 0.75 로 내린다. 대신 자동 불인정은 하지 않고 '확인필요'까지만 올린다
    #     (상투적 조치문구는 원래 비슷할 수 있어 사람이 최종 판단해야 한다).
    DUP_TH = 0.75
    for rows in by_person.values():
        prev = []                                  # [(loose_body, loose_act, row)]
        for r in rows:
            lb, la = _loose(r.get("body") or ""), _loose(r.get("act") or "")
            hit, how, where, pct = None, "", "", 0.0
            for plb, pla, pr in prev:
                for cur, old, tag in ((lb, plb, "상담내용"), (la, pla, "조치내용")):
                    if len(cur) < 12 or len(old) < 12:
                        continue
                    ratio = 1.0 if cur == old else difflib.SequenceMatcher(None, old, cur).ratio()
                    if ratio >= DUP_TH and ratio > pct:
                        hit, how, where, pct = pr, ("동일" if ratio == 1.0 else "유사"), tag, ratio
                if pct == 1.0:
                    break
            prev.append((lb, la, r))
            if hit is None:
                continue
            fd = hit["pasdate"]
            r["reasons"] = list(r.get("reasons") or []) + [
                f"{where}이 {fd[:4]}.{fd[4:6]}.{fd[6:]} 건과 {how}({pct*100:.0f}%) — 중복(복사) 작성 소지"]
            r["fixes"] = list(r.get("fixes") or []) + [
                "복사 작성 여부 확인 — 실제 상담이면 해당 회차 내용으로 재작성"]
            if r["verdict"] == "인정":
                r["verdict"] = "확인필요"

    # ★여러 수급자에게 같은 문구를 붙여넣은 경우 — 사람별 검사로는 절대 안 잡힌다.
    #   3명 이상에게 똑같이 쓰인 40자 이상 문구만 잡는다(공통 안내 문구 과탐 방지).
    #   상담내용·조치내용 둘 다 본다. 2명 이상이면 표시(실측: 조치내용 한 문구가 18명에게 동일).
    shared = defaultdict(set)
    for name, rows in by_person.items():
        for r in rows:
            for f in ("body", "act"):
                v = _loose(r.get(f) or "")
                if len(v) >= 30:
                    shared[(f, v)].add(name)
    mass = {k for k, v in shared.items() if len(v) >= 2}
    for name, rows in by_person.items():
        for r in rows:
            for f, tag in (("body", "상담내용"), ("act", "조치내용")):
                key = (f, _loose(r.get(f) or ""))
                if key not in mass:
                    continue
                n = len(shared[key])
                r["reasons"] = list(r.get("reasons") or []) + [
                    f"같은 {tag}이 수급자 {n}명에게 동일하게 쓰임 — 일괄 복사 소지"]
                r["fixes"] = list(r.get("fixes") or []) + [
                    "수급자별 실제 상담 내용으로 재작성"]
                if r["verdict"] == "인정":
                    r["verdict"] = "확인필요"

    # 분기별 인정 건수 (인정 + 확인필요는 잠정 인정으로 세지 않음 → 별도 표기)
    qsum = {}
    for name, rows in by_person.items():
        q = defaultdict(lambda: {"ok": 0, "chk": 0, "no": 0, "out": 0})
        for r in rows:
            k = _q(r["pasdate"])
            key2 = {"인정": "ok", "확인필요": "chk", "불인정": "no", "제외(퇴소)": "out"}[r["verdict"]]
            q[k][key2] += 1
        qsum[name] = {f"{y}-{n}Q": v for (y, n), v in sorted(q.items())}
    # 분기 미충족: 재원한 분기인데 '인정' 상담이 0건 (확인필요는 잠정 미충족으로 같이 표기)
    from datetime import date as _date
    today = _date.today()
    y0 = int(d["from"][:4])
    gout = _grade_out_periods(d["branch"])   # 등급 이력(등급외 기간) — gaps 제외용
    gaps = []
    for p in d["people"]:
        st = str(p.get("start") or "")
        en = str(p.get("end") or "")
        rows = by_person.get(p["name"], [])
        segs = gout.get(p["name"], [])
        for y in range(y0, today.year + 1):
            for qn in range(1, 5):
                qs = f"{y}{qn * 3 - 2:02d}01"
                qe = f"{y}{qn * 3:02d}31"
                if qe > today.strftime("%Y%m%d"):
                    continue                      # 진행 중 분기는 판단 보류
                if st and st > qe:
                    continue                      # 급여개시 전
                if en and en < qs and str(p.get("stat")) != "1":
                    continue                      # 퇴소 후
                # 등급외: 그 분기와 겹치는 등급구간이 '전부' 등급외면 급여 수급자 아님 → 상담 의무 없음(제외).
                # 분기 중 일부라도 등급이 있었으면(수급자였으면) 제외하지 않는다.
                ov = [g for g in segs if g[0] <= qe and g[1] >= qs]
                if ov and all(g[2] for g in ov):
                    continue
                # 분기 마지막 달(3·6·9·12월) 입소자는 그 분기 상담 제외 가능 — 재원기간이 짧아
                # 분기 내 상담 실시가 어렵다(사용자 확정 2026-07-29). 그 분기만 미충족에서 뺀다.
                if st and len(st) == 8 and qs <= st <= qe and int(st[4:6]) == qn * 3:
                    continue
                got = [r for r in rows if _q(r["pasdate"]) == (y, qn)]
                ok = sum(1 for r in got if r["verdict"] == "인정")
                chk = sum(1 for r in got if r["verdict"] == "확인필요")
                if ok == 0:
                    tail = ""
                    if st and qs <= st <= qe:      # 그 분기에 급여 개시 — 재원일수가 짧을 수 있음
                        tail = f" · 개시 {st[:4]}.{st[4:6]}.{st[6:]}"
                    gaps.append({"name": p["name"], "q": f"{y}-{qn}Q", "total": len(got),
                                 "ok": ok, "chk": chk, "start_in_q": bool(tail),
                                 "why": ("상담 자체 없음" + tail if not got else
                                         (f"확인필요 {chk}건뿐" if chk else "인정 상담 0건(전부 불인정·퇴소건)"))})
    d["review"] = {"by_person": by_person, "quarter": qsum, "gaps": gaps}
    return d


def render(key: str, d: dict) -> str:
    by_person = d["review"]["by_person"]
    qsum = d["review"]["quarter"]
    people = {p["name"]: p for p in d["people"]}
    allrows = [r for v in by_person.values() for r in v]
    cnt = Counter(r["verdict"] for r in allrows)
    noact = sum(1 for r in allrows if not r["act"])

    css = """
    body{font-family:'Malgun Gothic',sans-serif;margin:0;background:#f6f7f9;color:#222}
    .wrap{max-width:1100px;margin:0 auto;padding:24px}
    h1{font-size:22px;margin:0 0 4px} .sub{color:#666;font-size:13px;margin-bottom:18px}
    .kpi{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:20px}
    .kpi div{background:#fff;border:1px solid #e2e5ea;border-radius:8px;padding:10px 14px;font-size:13px}
    .kpi b{display:block;font-size:20px;margin-top:2px}
    .person{background:#fff;border:1px solid #e2e5ea;border-radius:10px;margin-bottom:14px;overflow:hidden}
    .phead{padding:10px 14px;background:#eef1f5;font-weight:700;font-size:15px;display:flex;gap:10px;align-items:center}
    .phead span.q{font-weight:400;font-size:12px;color:#555}
    .c{border-top:1px solid #eee;padding:12px 14px}
    .meta{font-size:12px;color:#555;margin-bottom:6px}
    .tag{display:inline-block;border-radius:4px;padding:1px 7px;font-size:12px;font-weight:700;margin-right:6px}
    .v인정{background:#e4f5e6;color:#1c6b2b} .v확인필요{background:#fff3d6;color:#8a6100}
    .v불인정{background:#fde2e2;color:#a11d1d} .v제외{background:#e8e8ef;color:#4a4a66}
    pre{white-space:pre-wrap;word-break:break-word;font-family:inherit;font-size:13px;
        background:#fafbfc;border:1px solid #eceff3;border-radius:6px;padding:9px 11px;margin:4px 0}
    .act{background:#f7fbff;border-color:#dbe9f7}
    .empty{color:#a11d1d;font-weight:700}
    .fix{font-size:12.5px;color:#7a1f1f;margin-top:6px}
    .fix li{margin:2px 0}
    """
    out = [f"<meta charset='utf-8'><title>상담일지 검수 — {key}</title><style>{css}</style>",
           "<div class='wrap'>",
           f"<h1>상담일지 내용 검수 — {d['branch']}</h1>",
           f"<div class='sub'>기간 {d['from']}~{d['to']} · 수급자 {len(d['people'])}명(퇴소자 포함) · "
           f"상담 {len(allrows)}건 · 케어포 1-4 상담일지 전문 발췌</div>",
           "<div class='kpi'>",
           f"<div>인정<b>{cnt['인정']}</b></div>",
           f"<div>확인필요<b>{cnt['확인필요']}</b></div>",
           f"<div>불인정<b>{cnt['불인정']}</b></div>",
           f"<div>제외(퇴소)<b>{cnt['제외(퇴소)']}</b></div>",
           f"<div>조치내용 공란<b>{noact}</b></div>",
           "</div>"]

    gaps = d["review"].get("gaps") or []
    if gaps:
        g_by = defaultdict(list)
        for g in gaps:
            g_by[g["name"]].append(g)
        out.append("<div class='person'><div class='phead'>⚠ 분기 미충족 후보 "
                   f"<span class='q'>{len(g_by)}명 / {len(gaps)}개 분기 — 해당 분기에 '인정' 상담 0건</span></div>"
                   "<div class='c' style='font-size:13px'>")
        for name in sorted(g_by):
            out.append(f"<div style='margin:3px 0'><b>{html.escape(name)}</b> — "
                       + ", ".join(f"{g['q']}({g['why']})" for g in g_by[name]) + "</div>")
        out.append("</div></div>")

    for name in sorted(by_person, key=lambda n: (-sum(1 for r in by_person[n] if r["verdict"] == "불인정"), n)):
        rows = by_person[name]
        p = people.get(name, {})
        stat = {"1": "수급중", "X": "퇴소", "E": "종료"}.get(str(p.get("stat")), str(p.get("stat") or ""))
        qtxt = " · ".join(f"{k}: 인정{v['ok']}/확인{v['chk']}/불인정{v['no']}"
                          + (f"/퇴소{v['out']}" if v["out"] else "")
                          for k, v in qsum.get(name, {}).items())
        out.append(f"<div class='person'><div class='phead'>{html.escape(name)} "
                   f"<span class='q'>{stat} · {len(rows)}건 · {html.escape(qtxt)}</span></div>")
        for r in rows:
            v = r["verdict"]
            vc = "v제외" if v.startswith("제외") else f"v{v}"
            dt = r["pasdate"]
            dts = f"{dt[:4]}.{dt[4:6]}.{dt[6:]}"
            out.append("<div class='c'>")
            out.append(f"<div class='meta'><span class='tag {vc}'>{v}</span>"
                       f"{dts} · {html.escape(clean(r.get('pasgbct')) or '-')} · "
                       f"{html.escape(r.get('pascway') or '-')} · 직원 {html.escape(r.get('stmname') or '-')} · "
                       f"대상 {html.escape(r.get('pasobjt') or '-')}({html.escape(r.get('pasobrl') or '-')})</div>")
            out.append(f"<pre>{html.escape(r['body']) or '(상담내용 공란)'}</pre>")
            out.append(f"<pre class='act'><b>조치내용</b>\n"
                       + (html.escape(r['act']) if r['act'] else "<span class='empty'>(공란 — 작성 필요)</span>")
                       + "</pre>")
            if r["reasons"]:
                out.append("<div class='fix'><b>지적</b>: " + " / ".join(html.escape(x) for x in r["reasons"])
                           + "<ul>" + "".join(f"<li>{html.escape(x)}</li>" for x in r["fixes"]) + "</ul></div>")
            out.append("</div>")
        out.append("</div>")
    out.append("</div>")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("branch")
    a = ap.parse_args()
    d = build(a.branch)
    o = out_dir(a.branch)
    (o / f"상담일지_검수_{a.branch}.html").write_text(render(a.branch, d), encoding="utf-8")
    slim = {"branch": d["branch"], "from": d["from"], "to": d["to"],
            "quarter": d["review"]["quarter"], "gaps": d["review"]["gaps"],
            "rows": [{k: r[k] for k in ("pamname", "pasdate", "pasgbct", "pascway", "stmname",
                                        "pasobjt", "pasobrl", "verdict", "reasons", "fixes", "body", "act")}
                     for v in d["review"]["by_person"].values() for r in v]}
    (o / f"상담일지_검수_{a.branch}.json").write_text(json.dumps(slim, ensure_ascii=False, indent=1), encoding="utf-8")
    c = Counter(r["verdict"] for r in slim["rows"])
    print(f"{d['branch']} 상담 {len(slim['rows'])}건 → " + " · ".join(f"{k} {v}" for k, v in c.most_common()))
    print(f"저장: {o / f'상담일지_검수_{a.branch}.html'}")


if __name__ == "__main__":
    main()
