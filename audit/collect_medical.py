# -*- coding: utf-8 -*-
"""항목 30① 의료기관 동행 진료내용 기록 자동판정 보조.

수급자가 급여제공시간 내 종사자 동행 의료기관 진료를 받은 내용을 기록했는지(4-4 병의원 진료내역 리포트).
평가 리스크: 동행/작성자가 자격자(간호사·(사회)복지사·시설장/센터장·요양보호사)가 아닌
사무원·운전원일 경우 문제 → 작성자 직종을 8-1 직원정보와 대조해 지적.
추가: 진료일에 그 수급자가 프로그램 참여로도 기록됐는지 날짜 겹침 표시(4-4에 진료 '시간' 없음 → 시간 겹침 판정 불가).

소스: 4-4 /share/nursing/view.nursing_hospital_report, 8-1 /staff/view.staff_manage
"""
import re

HOSP_VIEW = "/share/nursing/view.nursing_hospital_report"
STAFF_VIEW = "/staff/view.staff_manage"
PROG_VIEW = "/share/program/view.program_record"   # 5-7 수급자 참여프로그램 리포트
# 자격 미달(동행/작성 부적격) 직종 키워드
BAD_JOB_KEYS = ("사무", "운전")


def _set_period(page, sdate, edate):
    """s_date/e_date input 채우고 '조회' 버튼 클릭(리포트별 load 함수 자동 호출). YYYYMMDD 입력."""
    page.evaluate(
        """(a)=>{
          const s=document.querySelector('input[name=s_date]'), e=document.querySelector('input[name=e_date]');
          if(s) s.value=a.s; if(e) e.value=a.e;
          const btn=[...document.querySelectorAll('.m_button,button,a,span')]
            .find(x=>(x.textContent||'').trim()==='조회' && x.offsetParent!==null);
          if(btn) btn.click();
        }""",
        {"s": f"{sdate[:4]}.{sdate[4:6]}.{sdate[6:8]}", "e": f"{edate[:4]}.{edate[4:6]}.{edate[6:8]}"})
    page.wait_for_timeout(4000)


def scrape_program(page, g_pammgno, sdate, edate, progress=print) -> dict:
    """5-7 수급자 참여프로그램 리포트 → {수급자명: set(YYYY.MM.DD)}. 진료일↔프로그램 겹침 대조용.
    열: 연번·수급자명·등급·제공일시(날짜 시간)·유형·프로그램·참여도·만족도·수행도·특이사항·진행자."""
    try:
        _spa(page, g_pammgno, "left_sub5", PROG_VIEW, "5-7.수급자 참여프로그램 리포트")
        _set_period(page, sdate, edate)
        cells = page.evaluate("()=>[...document.querySelectorAll('g-td')].map(x=>x.innerText.trim())")
        by_person, i = {}, 0
        dtm = re.compile(r"(\d{4}\.\d{2}\.\d{2})")
        while i + 3 < len(cells):
            if cells[i].isdigit() and re.fullmatch(r"[가-힣]{2,5}", cells[i + 1] or "") and dtm.search(cells[i + 3] or ""):
                name = cells[i + 1]
                d = dtm.search(cells[i + 3]).group(1)
                by_person.setdefault(name, set()).add(d)
                i += 12
            else:
                i += 1
        # set → list (JSON 저장 위해 호출측에서 변환). 여기선 set 반환.
        progress(f"  5-7 수급자 프로그램 참여 {sum(len(v) for v in by_person.values())}건 / {len(by_person)}명")
        return {k: sorted(v) for k, v in by_person.items()}
    except Exception as e:
        progress(f"  5-7 프로그램 참여 수집 실패: {e}")
        return {}


def _spa(page, g_pammgno, type_, view, title):
    from src.carefor_client import build_spa_hash, _navigate_spa
    _navigate_spa(page, f"https://dn.carefor.co.kr/#{build_spa_hash(type_, view, title, g_pammgno)}")
    page.wait_for_timeout(3000)


def scrape_staff_jobs(page, g_pammgno, progress=print) -> dict:
    """8-1 직원 정보관리 → {직원명: 담당직종}. 열: 연번·현황·직원명(td2)·성별·담당직종(td4)·입사일."""
    try:
        _spa(page, g_pammgno, "left_sub8", STAFF_VIEW, "8-1.직원 정보관리")
        rows = page.evaluate(
            "()=>[...document.querySelectorAll('table.frame_list_tbl tr.cr')]"
            ".map(tr=>[...tr.querySelectorAll('td')].map(x=>x.innerText.trim()))")
        jobs = {}
        for r in rows:
            if len(r) >= 5 and re.fullmatch(r"[가-힣]{2,5}", r[2] or ""):
                jobs[r[2]] = r[4]
        progress(f"  8-1 직원 {len(jobs)}명 직종 수집")
        return jobs
    except Exception as e:
        progress(f"  8-1 직원 직종 수집 실패: {e}")
        return {}


def scrape_hospital(page, g_pammgno, sdate: str, edate: str, progress=print) -> list:
    """4-4 병의원 진료내역 → [{date,name,hospital,content,writer}]. 11컬럼 고정 그리드.
    sdate/edate = 'YYYYMMDD'. 기간을 평가기간으로 넓힌다."""
    try:
        _spa(page, g_pammgno, "left_sub4", HOSP_VIEW, "4-4.병의원 진료내역 리포트")
        # 기간 확대: s_date/e_date input 채우고 load_contents_form('nursingHospitalReport') 호출(확인됨)
        page.evaluate(
            """(a)=>{
              const s=document.querySelector('input[name=s_date]'), e=document.querySelector('input[name=e_date]');
              if(s) s.value=a.s; if(e) e.value=a.e;
              if(typeof load_contents_form==='function') load_contents_form('nursingHospitalReport');
            }""",
            {"s": f"{sdate[:4]}.{sdate[4:6]}.{sdate[6:8]}", "e": f"{edate[:4]}.{edate[4:6]}.{edate[6:8]}"})
        page.wait_for_timeout(4000)
        cells = page.evaluate("()=>[...document.querySelectorAll('g-td')].map(x=>x.innerText.trim())")
        recs = []
        i = 0
        date_re = re.compile(r"^\d{4}\.\d{2}\.\d{2}$")
        while i + 5 < len(cells):
            # 레코드 시작: [연번(digit), 진료일(date), 수급자, 병의원, 진료내용, 작성자, ...]
            if cells[i].isdigit() and date_re.match(cells[i + 1] or ""):
                recs.append({"date": cells[i + 1], "name": cells[i + 2], "hospital": cells[i + 3],
                             "content": cells[i + 4], "writer": cells[i + 5]})
                i += 11
            else:
                i += 1
        progress(f"  4-4 병의원 진료내역 {len(recs)}건 ({sdate}~{edate})")
        return recs
    except Exception as e:
        progress(f"  4-4 진료내역 수집 실패: {e}")
        return []


CONSULT_VIEW = "/share/patient/view.patient_consult"   # 1-4 상담일지


def scrape_consult_samedays(page, g_pammgno, connect_rows, progress=print) -> list:
    """연계기록지(1-10) 작성일에 그 수급자 상담일지(1-4)가 있는지 same-day 대조.

    1-4 상담 상세는 헤더 없는 g-b라 구조 파싱 불가 → 수급자 클릭 후 화면의 모든 날짜(상담관련)를
    모아 작성일이 그 집합에 있나로 판정. '없음'은 확실(상담 관련 날짜에 작성일이 아예 없음),
    '있음'은 상담 존재(엄밀한 상담일=작성일 여부는 수기 확인 권장).
    connect_rows: parse_connect(...)['rows'] = [{name, written, ...}].
    반환: [{name, written, has_consult}]
    """
    targets = [(r["name"], r["written"]) for r in (connect_rows or []) if r.get("written")]
    if not targets:
        return []
    try:
        _spa(page, g_pammgno, "left_sub1", CONSULT_VIEW, "1-4.상담일지")
        page.evaluate("()=>{const l=[...document.querySelectorAll('label')].find(e=>/퇴소자 포함/.test(e.textContent));"
                      "if(l){const i=l.querySelector('input'); if(i&&!i.checked)i.click();}}")
        page.wait_for_timeout(2500)
    except Exception as e:
        progress(f"  1-4 상담일지 이동 실패: {e}")
        return []
    out = []
    dre = re.compile(r"20\d{2}\.\d{2}\.\d{2}")
    for name, written in targets:
        try:
            clicked = page.evaluate(
                "(nm)=>{const t=document.querySelector('#patient_consult_table');"
                "const tf=[...t.querySelectorAll('g-tf')].find(el=>{try{return JSON.parse(el.getAttribute('data-info')||'{}').pamname===nm}catch(e){return false}});"
                "if(tf){tf.click();return true;}return false;}", name)
            if not clicked:
                out.append({"name": name, "written": written, "has_consult": None})  # 1-4에 없음(현재 목록 밖)
                continue
            page.wait_for_timeout(1800)
            dates = set(page.evaluate("()=>[...document.body.innerText.matchAll(/20\\d{2}\\.\\d{2}\\.\\d{2}/g)].map(m=>m[0])"))
            out.append({"name": name, "written": written, "has_consult": written in dates})
        except Exception:
            out.append({"name": name, "written": written, "has_consult": None})
    ok = sum(1 for x in out if x["has_consult"])
    progress(f"  연계기록지↔상담 same-day: {len(out)}건 중 작성일 상담확인 {ok}건")
    return out


def _job_bad(job: str) -> bool:
    return bool(job) and any(k in job for k in BAD_JOB_KEYS)


def judge_item30_1(records: list, staff_jobs: dict, prog_by_person: dict | None = None) -> dict:
    """작성자 자격(사무원·운전원 지적) + 진료일↔같은 수급자 프로그램 참여 겹침.

    prog_by_person: {수급자명: [YYYY.MM.DD,...]} (5-7 참여프로그램). None이면 겹침 판정 생략.
    겹침 = 진료 간 날 그 수급자가 프로그램 참여로도 기록됨 → 모순 소지(수기 시간확인).
    """
    if not records:
        return {"status": "주의", "detail": "4-4 병의원 진료내역 없음(기간 내 동행 진료 없음 또는 수집 실패) — 수기 확인",
                "writers": {}, "bad_writers": [], "overlap": []}
    writers = {}
    for r in records:
        w = r["writer"] or "(미기재)"
        writers.setdefault(w, {"cnt": 0, "job": staff_jobs.get(w, "?")})
        writers[w]["cnt"] += 1
    bad_writers = [(w, v["job"], v["cnt"]) for w, v in writers.items() if _job_bad(v["job"])]
    unknown = [w for w, v in writers.items() if v["job"] == "?" and w != "(미기재)"]

    overlap = []
    if prog_by_person is not None:
        for r in records:
            days = set(prog_by_person.get(r["name"], []))
            if r["date"] in days:
                overlap.append(f"{r['name']} {r['date']}")

    # ⚠️ 케어포 4-4엔 '동행자' 필드가 없고 '작성자'(입력자)만 있다. 작성자가 운전·사무직이어도
    #    실제 동행 진료는 자격자(간호사 등)가 하고 운전·기록입력만 맡은 경우가 있어 작성자만으로
    #    미흡 확정은 오탐이다(실사례: 운전직 직원이 차량운행+기록입력, 실제 동행 진료는 간호사가 수행).
    #    → 운전/사무 작성건은 '주의(실제 동행자 자격 수기확인)'로만 표시하고 미흡 확정 안 함.
    #    프로그램 겹침·직종미매칭도 주의(수기 시간확인). (사용자 확정 2026-07-21)
    if bad_writers or overlap or unknown:
        status = "주의"
    else:
        status = "양호"
    wsum = ", ".join(f"{w}({v['job']}·{v['cnt']}건)" for w, v in writers.items())
    detail = f"[①동행진료 기록·작성자자격] 진료 {len(records)}건, 작성자: {wsum}"
    if bad_writers:
        detail += (" · ⚠주의 작성자 운전/사무직(실제 동행자 자격 수기확인 — 작성자는 운전지원·입력자일 수 있음): "
                   + ", ".join(f"{w}({j},{c}건)" for w, j, c in bad_writers))
    if unknown:
        detail += f" · 직종미매칭(수기확인): {', '.join(unknown[:5])}"
    if prog_by_person is not None:
        if overlap:
            detail += (f" · ★진료일에 프로그램 참여로도 기록 {len(overlap)}건(모순·수기 시간확인): "
                       + ", ".join(overlap[:6]) + ("…" if len(overlap) > 6 else ""))
        else:
            detail += " · 진료-프로그램 겹침 없음"
    return {"status": status, "detail": detail, "writers": writers,
            "bad_writers": bad_writers, "overlap": overlap}
