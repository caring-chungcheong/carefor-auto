# -*- coding: utf-8 -*-
"""2-9 수급자 외출 리포트 수집 + 프로그램(5-7) 시간 충돌 판정.

왜 필요한가 (2026-08-05 회원님 지적):
  4-4 병의원 진료내역에는 **시각이 없다**(열 자체가 없음, 실측). 그래서 '같은 날 병원+프로그램'은
  1,477건이나 나와도 실제 충돌인지 알 수 없었다.
  외출 리포트에는 **외출시간·복귀시간**이 있다 → 프로그램 시간과 겹치는지 진짜로 계산할 수 있다.
  게다가 프로그램 기록은 전건 **참여도까지 기재**돼 있어, 외출 중 시간대에 참여도가 적혀 있으면
  그건 '실제 참여했다'고 기록한 것이라 명백한 모순이다.

열 구성(실측 2026-08-05 청주, 머리글 14칸):
  [연번, 외출일, 외출시간, 복귀시간, 급여이용여부, 수급자명, 성별, 생년월일, 외출목적,
   행선지, 동행 보호자(관계·연락처), 작성자, 병원, 비고]
★함정: g-td 를 평면으로 훑으면 '비고'가 비어 있어 다음 레코드 앞에 붙는다. 그래서 칸수로
  자르지 말고 (연번=숫자, 다음칸=날짜, 그다음 2칸=시각) 패턴으로 잡아야 한다.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

OUT_VIEW = "/share/patient/view.patient_out_report"
OUT_TITLE = "2-9.수급자 외출 리포트"
PROG_VIEW2 = "/share/program/view.program_record"
NM = re.compile(r"(?:\([^)]{1,4}\))?[가-힣]{2,5}")
DATE = re.compile(r"^\d{4}\.\d{2}\.\d{2}$")
TIME = re.compile(r"^\d{1,2}:\d{2}$")


def _min(t: str) -> int | None:
    if not t or not TIME.match(t.strip()):
        return None
    h, m = t.strip().split(":")
    return int(h) * 60 + int(m)


def parse_outings(cells: list[str]) -> list[dict]:
    """g-td 배열 → 외출 기록. 앵커(연번+외출일+시각 2개)로 잡고 12칸만 읽는다."""
    out, i, n = [], 0, len(cells)
    while i + 12 < n:
        if (cells[i].isdigit() and DATE.match(cells[i + 1] or "")
                and TIME.match(cells[i + 2] or "") and TIME.match(cells[i + 3] or "")
                and NM.fullmatch(cells[i + 5] or "")):
            out.append({"date": cells[i + 1], "start": cells[i + 2], "end": cells[i + 3],
                        "paid": cells[i + 4], "name": cells[i + 5],
                        "purpose": cells[i + 8], "place": cells[i + 9],
                        "escort": cells[i + 10], "writer": cells[i + 11],
                        "hosp": cells[i + 12]})
            i += 13
        else:
            i += 1
    return out


def overlaps(outings: list[dict], programs: list[dict]) -> list[dict]:
    """외출 시간대와 프로그램 시간대가 실제로 겹치는 건.

    ★프로그램에 참여도가 기재된 건만 '모순'으로 본다 — 시간표만 깔려 있고 참여 기록이
      없으면 실제 참여했다고 볼 수 없기 때문이다.
    ★외출/복귀 시각이 없는 건은 판정하지 않는다(모르는 걸 지적으로 만들지 않는다).
    """
    from collections import defaultdict
    by = defaultdict(list)
    for p in programs:
        by[(p["name"], p["date"])].append(p)

    hits = []
    for o in outings:
        os_, oe = _min(o.get("start")), _min(o.get("end"))
        if os_ is None or oe is None:
            continue
        for p in by.get((o["name"], o["date"]), []):
            ps, pe = _min(p.get("s")), _min(p.get("e"))
            if ps is None or pe is None:
                continue
            ov = min(oe, pe) - max(os_, ps)
            if ov <= 0:
                continue
            hits.append({**o, "prog": p.get("prog"), "pstart": p.get("s"), "pend": p.get("e"),
                         "join": p.get("join"), "overlap_min": ov})
    return hits


# ────────────────────────────── 수집 (지점점검 본체용) ──────────────────────────────

ROW_CELLS_JS = """
() => {
  const f = document.querySelector('g-td');
  if (!f) return [];
  return [...f.parentElement.children].map(c => (c.innerText || '').trim());
}
"""
_strip = lambda s: re.sub(r"^\([^)]{1,4}\)", "", str(s or "")).strip()
PDT = re.compile(r"(\d{4}\.\d{2}\.\d{2})(?:\s+(\d{2}:\d{2})~(\d{2}:\d{2}))?")


def _months(sdate: str, edate: str):
    y, m = int(sdate[:4]), int(sdate[4:6])
    ey, em = int(edate[:4]), int(edate[4:6])
    while (y, m) <= (ey, em):
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        last = (date(ny, nm, 1) - timedelta(days=1)).day
        yield f"{y}{m:02d}01", f"{y}{m:02d}{last:02d}"
        y, m = ny, nm


def _wait_grid(page, tries=12):
    prev, stable = -1, 0
    for _ in range(tries):
        n = page.evaluate("()=>document.querySelectorAll('g-td').length")
        if n and n == prev:
            stable += 1
            if stable >= 2:
                return n
        else:
            stable = 0
        prev = n
        page.wait_for_timeout(800)
    return prev


def scrape_outings(page, g_pammgno, sdate, edate, progress=print) -> list[dict]:
    """2-9 외출 리포트 → 외출 기록 목록.

    ★함정 2개(둘 다 실측으로 데였다):
      1) '외출일' 칸은 g-td 가 아니어서 querySelectorAll('g-td') 로는 **날짜가 통째로 빠진다**
         → 첫 g-td 의 parentElement.children 으로 읽는다.
      2) 장기간을 한 번에 조회하면 열 구성이 바뀌어 날짜가 사라진다 → **월 단위로 끊어** 조회.
    """
    from .collect_medical import _spa, _set_period
    out = []
    try:
        _spa(page, g_pammgno, "left_sub2", OUT_VIEW, OUT_TITLE)
        for ms, me in _months(sdate, edate):
            _set_period(page, ms, me)
            _wait_grid(page)
            got = parse_outings(page.evaluate(ROW_CELLS_JS))
            for o in got:
                o["name"] = _strip(o["name"])
            out += got
        progress(f"  2-9 외출 기록 {len(out)}건")
    except Exception as e:
        progress(f"  2-9 외출 수집 실패: {e}")
    return out


def scrape_program_slots(page, g_pammgno, sdate, edate, progress=print) -> list[dict]:
    """5-7 프로그램 리포트 → 시각·참여도까지 담은 개별 기록.

    기존 scrape_program 은 {이름: [날짜]} 라 '같은 날'까지밖에 못 본다. 시간 충돌을 계산하려면
    제공일시의 **시각**과 **참여도**가 필요해서 따로 읽는다.
    """
    from .collect_medical import _spa, _set_period, PROG_VIEW
    slots = []
    try:
        _spa(page, g_pammgno, "left_sub5", PROG_VIEW, "5-7.수급자 참여프로그램 리포트")
        _set_period(page, sdate, edate)
        _wait_grid(page, tries=25)
        c = page.evaluate("()=>[...document.querySelectorAll('g-td')].map(x=>x.innerText.trim())")
        i = 0
        while i + 11 < len(c):
            m = PDT.search(c[i + 3] or "")
            if c[i].isdigit() and NM.fullmatch(c[i + 1] or "") and m:
                slots.append({"name": _strip(c[i + 1]), "date": m.group(1),
                              "s": m.group(2) or "", "e": m.group(3) or "",
                              "prog": c[i + 6], "join": c[i + 7]})
                i += 12
            else:
                i += 1
        progress(f"  5-7 프로그램(시각 포함) {len(slots)}건")
    except Exception as e:
        progress(f"  5-7 프로그램 시각 수집 실패: {e}")
    return slots


BAD_JOB = re.compile(r"사무원|운전|조리|위생|영양")
HOSP_RE = re.compile(r"병원|진료|의원|검사|처방|치과|한의원|내과|외과|안과|피부|비뇨")


def judge_outing(outings: list[dict], slots: list[dict], staff_jobs: dict) -> dict:
    """30① 보강 판정 — 외출 시각 기준 충돌 + 동행자 자격.

    ★판정은 **동행자**로만 한다. 작성자는 입력자일 뿐이라 자격과 무관하다
      (회원님 확인 2026-08-05: "작성자만 운전원이고 실제 동행자가 서비스 제공자면 문제 없음").
    ★둘 다 '주의'까지만 낸다 — 기록만으로 사실을 단정할 수 없어서다(입력 실수일 수 있다).
      미흡으로 밀면 오탐이 곧 감점이 된다.
    """
    if not outings:
        return {"status": None, "detail": "", "conflicts": [], "badjob": []}

    hits, seen = [], set()
    for h in overlaps(outings, slots):
        if not (h.get("join") or "").strip():
            continue                      # 참여도가 비면 실제 참여로 볼 수 없다
        k = (h["date"], h["name"], h["pstart"], str(h["prog"]))
        if k in seen:
            continue                      # 프로그램 기록 자체가 중복 등록된 건이 있다
        seen.add(k)
        hits.append(h)

    def job_of(escort: str) -> str:
        m = re.match(r"([가-힣]{2,5})", str(escort or ""))
        j = staff_jobs.get(m.group(1), "") if m else ""
        if not j:                         # 8-1 에 없으면 기록에 적힌 괄호 직종이라도 쓴다
            m2 = re.search(r"\((사무원|운전[^,)]*|조리원|위생원)", str(escort or ""))
            j = m2.group(1) if m2 else ""
        return j

    bad = []
    for o in outings:
        j = job_of(o.get("escort"))
        if j and BAD_JOB.search(j) and HOSP_RE.search(f"{o.get('purpose')}{o.get('place')}"):
            bad.append({**o, "job": j})

    parts = [f"외출 {len(outings)}건"]
    if hits:
        who = sorted({h["name"] for h in hits})
        parts.append(f"⚠외출 시간에 프로그램 참여도까지 기재된 건 {len(hits)}건"
                     f"(수급자 {len(who)}명: {', '.join(who[:6])}{'…' if len(who) > 6 else ''}) — 수기확인")
    else:
        parts.append("외출↔프로그램 시간 충돌 없음")
    if bad:
        who = sorted({f"{re.match(r'([가-힣]{2,5})', b['escort']).group(1)}({b['job']})"
                      for b in bad if re.match(r"([가-힣]{2,5})", b["escort"])})
        parts.append(f"⚠동행자가 자격 외 직종인 병원 동행 {len(bad)}건({', '.join(who)}) — "
                     "실제 동행자 수기확인(작성자는 판정 대상 아님)")
    return {"status": ("주의" if (hits or bad) else "양호"),
            "detail": " · ".join(parts), "conflicts": hits, "badjob": bad}
