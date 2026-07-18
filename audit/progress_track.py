# -*- coding: utf-8 -*-
"""지점점검 진행추적 — 매 런의 항목별 '상태'를 스냅샷으로 누적, 직전 대비 변화 산출.

왜 상태 기반인가 (사용자 확정 2026-07-18):
  "지점이 실제로 업무를 진행/개선하고 있는지 확인"이 목적. 총점은 본부가 수기로 매기는
  Apps Script 훅이라 자동이 아니다. 그래서 항목별 status(양호/주의/미흡)를 지표로 쓴다.
  항목이 미흡→양호로 '상태가 바뀌어야' 지점이 고친 것이다. 상세 건수·문구를 코드 개선으로
  손봐도 status 는 잘 안 흔들려, 오탐 수정과 '진짜 지점 개선'이 섞이지 않는다.

개인정보 없음: docs/audit_history.json 은 공개 저장소에 커밋된다. 항목번호·상태·건수 요약만
  담고 수급자명·상세는 절대 넣지 않는다(status 문자열만).

한계: git 대시보드 이력(07-09~)과 달리 이 스냅샷은 '이 기능 도입 이후'부터 누적된다. 그리고
  이번 주는 점검 코드 자체가 바뀌어(27·8③·20①·생일쿠폰·신체) 그 이전과는 비교가 오염된다 →
  코드가 안정된 2026-07-18 스냅샷을 첫 기준선으로 삼고, 월요일 런부터 깨끗하게 비교된다.
"""
from __future__ import annotations

import json
from pathlib import Path

HIST = Path(__file__).resolve().parent.parent / "docs" / "audit_history.json"
RANK = {"양호": 0, "주의": 1, "미흡": 2}   # 낮을수록 좋음 (개선=값 감소)


def _snap(data: dict) -> list[dict]:
    """AUDIT_DATA(마스킹본) → 지점별 스냅샷 [{date, branch, run_at, counts, items}]."""
    out = []
    for branch, v in (data or {}).items():
        if not isinstance(v, dict):
            continue
        ir = v.get("item_results") or {}
        run_at = (v.get("run_at") or "").strip()
        items, counts = {}, {}
        for it, r in ir.items():
            st = (r or {}).get("status") or "?"
            items[str(it)] = st
            counts[st] = counts.get(st, 0) + 1
        out.append({"date": run_at[:10], "branch": branch, "run_at": run_at,
                    "counts": counts, "items": items})
    return out


def record(data: dict, path: Path = HIST) -> int:
    """스냅샷을 히스토리에 append. 같은 (date, branch)면 run_at 최신으로 대체.

    하루 여러 번 돌아도 그 날짜 스냅샷은 최신 1개만 남는다(일 단위 추적).
    반환: 저장된 총 스냅샷 수.
    """
    snaps = _snap(data)
    hist: list[dict] = []
    if path.exists():
        try:
            hist = json.loads(path.read_text(encoding="utf-8")).get("snapshots", [])
        except (json.JSONDecodeError, OSError):
            hist = []
    idx = {(s["date"], s["branch"]): i for i, s in enumerate(hist)}
    for s in snaps:
        if not s["date"]:
            continue                      # run_at 없는 건 기록하지 않음
        k = (s["date"], s["branch"])
        if k in idx:
            if s["run_at"] >= hist[idx[k]].get("run_at", ""):
                hist[idx[k]] = s
        else:
            hist.append(s)
    hist.sort(key=lambda s: (s["branch"], s["date"]))
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({"snapshots": hist}, ensure_ascii=False), encoding="utf-8")
    return len(hist)


def compare(path: Path = HIST) -> dict:
    """지점별 최신 vs 직전(다른 날) 스냅샷 → 개선/후퇴 항목.

    반환: {지점: {prev_date, cur_date, improved:[(항목,전,후)], regressed:[...]}}.
    직전 스냅샷이 없으면(첫 기록) improved/regressed 는 빈 리스트.
    """
    if not path.exists():
        return {}
    try:
        hist = json.loads(path.read_text(encoding="utf-8")).get("snapshots", [])
    except (json.JSONDecodeError, OSError):
        return {}
    by_branch: dict[str, list] = {}
    for s in hist:
        by_branch.setdefault(s["branch"], []).append(s)
    result = {}
    for branch, snaps in by_branch.items():
        snaps.sort(key=lambda s: s["date"])
        cur = snaps[-1]
        if len(snaps) < 2:
            result[branch] = {"prev_date": None, "cur_date": cur["date"],
                              "improved": [], "regressed": []}
            continue
        prev = snaps[-2]
        improved, regressed = [], []
        for it, st in cur["items"].items():
            old = prev["items"].get(it)
            if old is None or old == st:
                continue
            if RANK.get(st, 9) < RANK.get(old, 9):
                improved.append((it, old, st))
            elif RANK.get(st, 9) > RANK.get(old, 9):
                regressed.append((it, old, st))
        improved.sort(key=lambda x: int(x[0]) if x[0].isdigit() else 99)
        regressed.sort(key=lambda x: int(x[0]) if x[0].isdigit() else 99)
        result[branch] = {"prev_date": prev["date"], "cur_date": cur["date"],
                          "improved": improved, "regressed": regressed}
    return result


def print_report(path: Path = HIST) -> None:
    """CI 로그용 진행추적 요약 출력."""
    cmp = compare(path)
    if not cmp:
        print("  진행추적: 스냅샷 없음")
        return
    for branch in sorted(cmp):
        c = cmp[branch]
        if not c["prev_date"]:
            print(f"  [{branch}] 진행추적 첫 기준선({c['cur_date']}) — 다음 런부터 변화 표시")
            continue
        imp = ", ".join(f"항목{it}({o}→{n})" for it, o, n in c["improved"]) or "없음"
        reg = ", ".join(f"항목{it}({o}→{n})" for it, o, n in c["regressed"]) or "없음"
        print(f"  [{branch}] {c['prev_date']}→{c['cur_date']} · 개선 {len(c['improved'])}: {imp}"
              f" / 후퇴 {len(c['regressed'])}: {reg}")


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    print_report()
