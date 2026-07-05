# -*- coding: utf-8 -*-
"""지점점검 자체 테스트 도구 (더블클릭 실행용).

지점점검_테스트.bat 을 더블클릭하면 메뉴가 뜹니다.
명령줄로도 사용 가능:
  py -X utf8 지점점검_테스트.py --quick 천안점   # 3명 빠른 테스트
  py -X utf8 지점점검_테스트.py --full 천안점    # 한 지점 전체
"""
from __future__ import annotations

import argparse
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

from src.config import Config, config_path
from audit.items import BRANCH_CUTOFFS


def run_branch(branch_name: str, limit: int = 0) -> bool:
    from audit.collector import run_branch_audit

    cfg = Config.load(config_path())
    b = next((x for x in cfg.branches if branch_name in x.name), None)
    if not b:
        print(f"  ❌ 지점 '{branch_name}' 을 설정에서 찾을 수 없습니다.")
        return False
    cutoff = BRANCH_CUTOFFS.get(b.name, "2024.01.01")
    label = f"{b.name} ({'빠른 테스트: 수급자 ' + str(limit) + '명' if limit else '전체'})"
    print(f"\n▶ {label} 점검 시작 — 기준일 {cutoff}")
    print("  (창 없이 백그라운드로 케어포에 접속합니다. 잠시 기다려주세요...)\n")
    try:
        # 빠른 테스트(limit>0)는 저장 안 함 — 정기 점검 데이터를 덮어쓰지 않도록
        out = run_branch_audit(ctmnumb=b.ctmnumb, branch_name=b.name, cutoff=cutoff,
                               limit=limit, headless=True, save=(limit == 0))
    except Exception as e:
        print(f"\n  ❌ 실패: {e}")
        traceback.print_exc()
        return False

    print(f"\n===== {b.name} 판정 결과 =====")
    ok = bad = 0
    for no in sorted(out["item_results"], key=int):
        r = out["item_results"][no]
        mark = "🟢" if r["status"] == "양호" else "🔴"
        if r["status"] == "양호":
            ok += 1
        else:
            bad += 1
        print(f"  {mark} 항목 {no}: {r['status']} — {r['detail']}")
    print(f"\n  ✅ 테스트 성공 — 자동판정 {ok + bad}개 항목 (양호 {ok} / 미흡 {bad})")
    if limit:
        print("  ⚠️ 빠른 테스트라 수급자 항목(20~22)은 일부 인원 기준입니다. 실제 수치는 전체 점검으로 확인하세요.")
    return True


def open_dashboard() -> None:
    dash = BASE / "audit_dashboard.html"
    os.startfile(str(dash))
    print(f"  대시보드를 열었습니다: {dash.name}")


def show_status() -> None:
    print("\n===== 최근 점검 데이터 =====")
    res_dir = BASE / "audit_results"
    found = False
    for f in sorted(res_dir.glob("*.json")):
        try:
            import json
            d = json.loads(f.read_text(encoding="utf-8"))
            n_items = len(d.get("item_results", {}))
            print(f"  {d.get('branch', f.stem)}: {d.get('run_at', '?')} 실행 · 수급자 {d.get('people', '?')}명 · 자동판정 {n_items}개")
            found = True
        except Exception:
            continue
    if not found:
        print("  아직 점검 데이터가 없습니다.")


def pick_branch(cfg) -> str | None:
    print("\n지점을 선택하세요:")
    for i, b in enumerate(cfg.branches, 1):
        print(f"  {i}. {b.name}")
    sel = input("번호 입력: ").strip()
    if sel.isdigit() and 1 <= int(sel) <= len(cfg.branches):
        return cfg.branches[int(sel) - 1].name
    print("  잘못된 입력입니다.")
    return None


def menu() -> None:
    cfg = Config.load(config_path())
    while True:
        print("\n" + "=" * 46)
        print("       🏥 지점점검 자체 테스트 도구")
        print("=" * 46)
        print("  1. 빠른 동작 테스트 (수급자 3명만 — 약 3분)")
        print("  2. 한 지점 전체 점검 (10~20분)")
        print("  3. 4개 지점 전체 점검 (1시간 안팎)")
        print("  4. 최근 점검 데이터 확인")
        print("  5. 결과 대시보드 열기")
        print("  0. 종료")
        sel = input("\n선택: ").strip()

        if sel == "1":
            b = pick_branch(cfg)
            if b:
                run_branch(b, limit=3)
        elif sel == "2":
            b = pick_branch(cfg)
            if b and input(f"  {b} 전체 점검은 10~20분 걸립니다. 진행? (y/n): ").strip().lower() == "y":
                run_branch(b)
        elif sel == "3":
            if input("  4개 지점 전체는 1시간 정도 걸립니다. 진행? (y/n): ").strip().lower() == "y":
                for b in cfg.branches:
                    run_branch(b.name)
        elif sel == "4":
            show_status()
        elif sel == "5":
            open_dashboard()
        elif sel == "0":
            break


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", help="지점명 — 3명 빠른 테스트")
    ap.add_argument("--full", help="지점명 — 전체 점검")
    args = ap.parse_args()

    if args.quick:
        sys.exit(0 if run_branch(args.quick, limit=3) else 1)
    if args.full:
        sys.exit(0 if run_branch(args.full) else 1)
    menu()


if __name__ == "__main__":
    main()
