# -*- coding: utf-8 -*-
"""전월 평균 입소자 폴백 저장소.

케어포 2-8 전월 수집이 순간적으로 실패해도 출석보고에 빈칸·오값이 나가지 않게,
'그 달의 전월값'(마감이라 한 달 내내 고정)을 저장해두고 실패 시 재사용한다.
키 = 보고 연월('YYYY-MM'), 값 = {지점명: 전월 최종 평균}.

- 라이브 수집 성공 → 그 값을 쓰고 저장소도 갱신(save).
- 라이브 실패(None) → 같은 달 저장값을 폴백으로 사용(resolve).
- 저장값도 없으면 None(이미지에선 전월줄만 생략 — 틀린 숫자는 절대 안 씀).

⚠️ CI(GitHub Actions)는 런마다 새 러너라 write 가 안 남는다 → **커밋된 파일이 폴백의 진실**.
   매달 라이브가 정상 수집되면 갱신 불필요하지만, 안전그물로 월초 검증값을 커밋해둔다.
"""
from __future__ import annotations

import json
from pathlib import Path

_STORE = Path(__file__).resolve().parent.parent / "attendance_prev_avg.json"


def load() -> dict:
    try:
        return json.loads(_STORE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def resolve(store: dict, month_key: str, name: str, live: float | None) -> float | None:
    """라이브값이 있으면 그것, 없으면 같은 달 저장 폴백값(없으면 None)."""
    if live is not None:
        return live
    return (store.get(month_key) or {}).get(name)


def save(store: dict, month_key: str, name: str, live: float | None) -> None:
    """라이브 성공값을 저장소에 반영(다음 실패 대비). 쓰기 실패는 무시."""
    if live is None:
        return
    if store.get(month_key, {}).get(name) == live:
        return
    store.setdefault(month_key, {})[name] = live
    try:
        _STORE.write_text(json.dumps(store, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        pass
