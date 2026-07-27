"""GitHub Actions 에서 근무일지 점검을 돌리는 headless 래퍼 (월 1회 자동 실행).

`audit/collect_work_report.py` 는 로컬 전제(keyring 자격증명 + config_path() 의 config.yaml)라
CI 러너에서 그대로 못 돈다. revenue_check_headless.py 와 같은 방식으로
환경변수(Secrets) → credentials 패치 + CONFIG_YAML 파일화를 먼저 해준다.

⚠️ 산출물(근무일지점검_*.html, audit_results/work_report_*.json)에는 **직원 실명**이 들어 있다.
   러너 안에서만 쓰고 저장소에 커밋하지 않는다(.gitignore 로 이중 차단).
   허브에는 도메인(caring.co.kr) 제한으로만 서빙된다.

사용: python work_report_headless.py [YYYY-MM|prev]     (기본 prev = 전월)
출력: GITHUB_OUTPUT 에 combined=<합본 HTML 경로>
"""
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

# ── 환경변수 → credentials 패치 (keyring 우회) ──────────────────────────
import src.credentials as _creds

_env_map = {
    _creds.KEY_PORTAL_ID:       os.environ.get("CAREFOR_ID"),
    _creds.KEY_PORTAL_PASSWORD: os.environ.get("CAREFOR_PW"),
}
_original_get = _creds.get


def _patched_get(key: str) -> str | None:
    v = _env_map.get(key)
    return v if v else _original_get(key)


_creds.get = _patched_get

# ── config.yaml 준비 ────────────────────────────────────────────────────
from src.config import config_path  # noqa: E402

_cfg_yaml = os.environ.get("CONFIG_YAML")
if _cfg_yaml:
    _p = config_path()
    _p.parent.mkdir(parents=True, exist_ok=True)
    _p.write_text(_cfg_yaml, encoding="utf-8")

if not config_path().exists():
    print("ERROR: config.yaml 이 없습니다 (CONFIG_YAML 환경변수 미설정).", flush=True)
    sys.exit(1)

from datetime import date  # noqa: E402

from src.config import Config  # noqa: E402
from audit.collect_work_report import run, prev_ym  # noqa: E402
from audit import make_work_report_check  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent / "audit_results" / "work_report_html"


def main() -> None:
    arg = sys.argv[1] if len(sys.argv) > 1 else "prev"
    today = date.today()
    ym = prev_ym(today) if arg in ("", "prev") else arg
    print(f"근무일지 점검 — 대상 월 {ym}", flush=True)

    cfg = Config.load(config_path())
    ok = 0
    for b in cfg.branches:
        # ★케어포는 단일 계정 — 반드시 지점 순차. 한 지점이 실패해도 나머지는 진행한다.
        try:
            run(b.name, None, today, ym=ym)
            ok += 1
        except Exception as e:                       # noqa: BLE001
            print(f"  ⚠️ {b.name} 수집 실패: {e}", flush=True)

    if not ok:
        print("ERROR: 모든 지점 수집 실패 — 허브 갱신 안 함", flush=True)
        sys.exit(1)

    sys.argv = ["make_work_report_check", "--ym", ym, "--out", str(OUT_DIR)]
    make_work_report_check.main()


if __name__ == "__main__":
    main()
