# -*- coding: utf-8 -*-
"""근무일지 점검 리포트 생성 — collect_work_report 결과(JSON) → 지점별 HTML + 합본.

사전: py -X utf8 -m audit.collect_work_report --all
사용: py -X utf8 -m audit.make_work_report_check

저장: 바탕화면/클로드코드/근무일지점검/<지점>/근무일지점검_<지점>_<날짜>.html
      바탕화면/클로드코드/근무일지점검/근무일지점검_합본_<날짜>.html
★직원 실명이 들어가므로 저장소에 커밋하지 않는다.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from src.config import Config, config_path

IN_DIR = Path(__file__).resolve().parent.parent / "audit_results"


def default_out_root() -> Path:
    """기본 저장 폴더 — 로컬은 바탕화면/클로드코드/근무일지점검.
    ★deskpath 는 로컬 전용(커밋 안 된) 모듈이라 CI 러너엔 없다 → 러너 경로로 폴백한다
      (import 를 모듈 최상단에 두면 CI 가 import 단계에서 죽는다 — 실측 2026-07-27)."""
    try:
        from .deskpath import DESK
        return DESK / "근무일지점검"
    except ImportError:
        return IN_DIR / "work_report_html"

CSS = """
body{font-family:'맑은 고딕',Malgun Gothic,sans-serif;margin:24px;color:#222;background:#fafafa}
h1{font-size:20px;margin:0 0 4px} h2{font-size:16px;margin:26px 0 8px;border-left:4px solid #4b7bec;padding-left:8px}
.sub{color:#666;font-size:12px;margin-bottom:16px}
table{border-collapse:collapse;width:100%;background:#fff;font-size:13px;margin-bottom:8px}
th,td{border:1px solid #ddd;padding:6px 8px;text-align:center}
th{background:#f0f3f7}
td.l{text-align:left}
.ok{color:#1e9e4a;font-weight:bold} .bad{color:#d63031;font-weight:bold} .warn{color:#e17055;font-weight:bold}
.days{font-size:12px;color:#444;text-align:left;line-height:1.7}
.day{display:inline-block;background:#ffecec;border:1px solid #f5b7b1;border-radius:3px;
     padding:1px 5px;margin:1px 2px;white-space:nowrap}
.note{background:#fff8e1;border:1px solid #ffe082;padding:10px 12px;font-size:12px;margin:12px 0;line-height:1.7}
.mini{font-size:11px;color:#888}
"""

RULE = """<div class="note">
<b>판정 기준</b><br>
· 대상 직종: 시설장(관리책임자)·사무원·간호(조무)사·사회복지사 (요양보호사·운전사·조리원 제외)<br>
· 대상 기간: {period} (직원별로는 입사일 이후). <b>퇴사자 제외</b>(케어포 8-4 재직자 목록 기준)<br>
· <b>근무일정(근)이 잡힌 날만 작성 대상</b> — 일요일·공휴일·휴무일은 일정이 없으면 대상 아님.
  토요일·공휴일도 그 날 근무일정이 있으면(=근무자) 대상에 포함<br>
· 작성 여부: 케어포 8-4 달력의 '근무일지' 버튼 상태(작성완료 표시). 실제 저장된 일지가 있는 날만 작성으로 집계<br>
· 오늘 날짜는 퇴근 후 작성이 정상이라 판정에서 제외
</div>"""


def _fmt(d: str) -> str:
    return f"{d[4:6]}/{d[6:8]}" if len(d) == 8 else d


def _branch_html(data: dict) -> str:
    rows, detail = [], []
    tt = tw = 0
    for s in sorted(data["staff"], key=lambda x: -len(x["missing"])):
        n_miss = len(s["missing"])
        tt += s["target_days"]
        tw += s["written_days"]
        rate = (s["written_days"] / s["target_days"] * 100) if s["target_days"] else 0
        cls = "ok" if n_miss == 0 else ("bad" if n_miss >= 5 else "warn")
        rows.append(
            f"<tr><td class='l'>{s['name']}</td><td>{s['job']}</td>"
            f"<td>{s['joined'][:4]}.{s['joined'][4:6]}</td>"
            f"<td>{s['from']} ~ {s['to']}</td>"
            f"<td>{s['target_days']}</td><td>{s['written_days']}</td>"
            f"<td class='{cls}'>{n_miss}</td><td>{rate:.1f}%</td></tr>")
        if n_miss:
            # 월별로 묶어 표기
            by_m: dict[str, list] = {}
            for m in s["missing"]:
                by_m.setdefault(m["date"][:6], []).append(m)
            blocks = []
            for ym, ds in sorted(by_m.items()):
                chips = " ".join(f"<span class='day'>{_fmt(d['date'])}"
                                 + (f" {d['label'].split(' ')[1]}" if len(d["label"].split(" ")) > 1 else "")
                                 + "</span>" for d in ds)
                blocks.append(f"<b>{ym[:4]}.{ym[4:6]}</b> ({len(ds)}일)<br>{chips}")
            detail.append(f"<h2>{s['name']} · {s['job']} — 누락 {n_miss}일</h2>"
                          f"<div class='days'>{'<br>'.join(blocks)}</div>")
        if s["no_sched"]:
            detail.append(f"<div class='mini'>※ {s['name']}: 근무일정 없이 출퇴근 기록만 있는 날 "
                          f"{len(s['no_sched'])}일 (일정 누락 의심 — 참고) : "
                          + ", ".join(_fmt(x["date"]) for x in s["no_sched"][:20]) + "</div>")
        if s["failed_months"]:
            detail.append(f"<div class='mini'>※ {s['name']}: 수집 실패 월 "
                          + ", ".join(s["failed_months"]) + " (재수집 필요)</div>")

    total_miss = sum(len(s["missing"]) for s in data["staff"])
    head = (f"<h1>근무일지 점검 — {data['branch']}</h1>"
            f"<div class='sub'>대상기간 {data['since']} ~ {data.get('until', '?')} · "
            f"수집일 {data.get('run_at', '?')} · 대상 {len(data['staff'])}명 · "
            f"작성대상 {tt}일 중 <b class='{'ok' if total_miss == 0 else 'bad'}'>누락 {total_miss}일</b></div>")
    table = ("<table><tr><th>직원명</th><th>담당직종</th><th>입사</th><th>점검기간</th>"
             "<th>작성대상일</th><th>작성</th><th>누락</th><th>작성률</th></tr>"
             + "".join(rows) + "</table>")
    period = f"{data['since']} ~ {data.get('until', '?')}"
    return head + RULE.format(period=period) + table + "".join(detail)


def _page(title: str, body: str) -> str:
    return (f"<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
            f"<title>{title}</title><style>{CSS}</style></head><body>{body}</body></html>")


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--ym", default=None, help="특정 월 결과 사용 YYYY-MM ('prev'=전월)")
    ap.add_argument("--out", default=None,
                    help="저장 폴더(기본: 바탕화면/클로드코드/근무일지점검). CI 는 러너 경로 지정")
    a = ap.parse_args()

    from .collect_work_report import prev_ym
    ym = prev_ym(date.today()) if a.ym == "prev" else a.ym
    out_root = Path(a.out) if a.out else default_out_root()

    cfg = Config.load(config_path())
    today = date.today().isoformat()
    out_root.mkdir(parents=True, exist_ok=True)
    all_body, summary, missing_branch = [], [], []
    for b in cfg.branches:
        key = b.name.replace(" ", "_") + (f"_{ym}" if ym else "")
        f = IN_DIR / f"work_report_{key}.json"
        if not f.exists():
            # ★조용히 빼면 '누락 0'처럼 보인다 — 합본에 '수집 실패'로 반드시 남긴다
            print(f"  건너뜀(수집 결과 없음): {b.name}")
            missing_branch.append(b.name)
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        body = _branch_html(data)
        d = out_root / b.name.replace(" ", "_")
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"근무일지점검_{b.name.replace(' ', '_')}_{ym or today}.html"
        p.write_text(_page(f"근무일지 점검 {b.name}", body), encoding="utf-8")
        print(f"  저장: {p}")
        all_body.append(body)
        miss = sum(len(s["missing"]) for s in data["staff"])
        tgt = sum(s["target_days"] for s in data["staff"])
        bad = [s["name"] for s in data["staff"] if s["missing"]]
        summary.append((b.name, len(data["staff"]), tgt, miss, bad))

    if all_body:
        rows = "".join(
            f"<tr><td class='l'>{n}</td><td>{c}</td><td>{t}</td>"
            f"<td class='{'ok' if m == 0 else 'bad'}'>{m}</td>"
            f"<td class='l'>{', '.join(b) or '-'}</td></tr>" for n, c, t, m, b in summary)
        rows += "".join(f"<tr><td class='l'>{n}</td><td colspan='4' class='bad'>"
                        f"수집 실패 — 이번 달 결과 없음(재실행 필요)</td></tr>"
                        for n in missing_branch)
        scope = f"{ym} 한 달" if ym else "개소일 ~ 현재 전체"
        top = (f"<h1>근무일지 점검 — 충청본부 합본</h1>"
               f"<div class='sub'>점검범위 {scope} · 수집 {today}</div>"
               "<table><tr><th>지점</th><th>대상 직원</th><th>작성대상일</th>"
               "<th>누락일</th><th>누락 있는 직원</th></tr>" + rows + "</table>")
        p = out_root / f"근무일지점검_합본_{ym or today}.html"
        p.write_text(_page("근무일지 점검 합본", top + "".join(all_body)), encoding="utf-8")
        print(f"  저장: {p}")
        # CI 가 허브 배포에 쓰도록 합본 경로를 GitHub 출력으로 넘긴다
        gh = os.environ.get("GITHUB_OUTPUT")
        if gh:
            with open(gh, "a", encoding="utf-8") as fh:
                fh.write(f"combined={p}\n")


if __name__ == "__main__":
    main()
