"""GitHub Actions 에서 실행되는 지점점검 headless 스크립트.

환경변수(Secrets)에서 자격증명을 읽어 4개 지점 점검 → 구글시트 업로드
→ 개인정보 없는 요약페이지(docs/audit_summary.html) 재생성.
개인정보가 포함된 audit_results/*.json 은 러너에서만 존재하고 저장소에 커밋되지 않는다.

환경변수:
  AUDIT_LIMIT   지점당 인원 제한 (0=전체)
  AUDIT_TEST    true = 저장·시트업로드·요약 전부 생략
  AUDIT_BRANCH  특정 지점만 (부분 일치, '전체'/빈값이면 전부)

  matrix 병렬화용 (기본값이면 기존 단일 러너 동작과 완전히 동일):
  AUDIT_SKIP_UPLOAD  true = 점검만 하고 구글시트 업로드는 하지 않는다.
                     지점별 job 이 각자 부분 결과를 올려 시트를 덮어쓰는 것을 막는다.
  AUDIT_MERGE        true = 케어포를 긁지 않고, 이미 audit_results/ 에 있는
                     지점 결과(<지점>.json)만 모아 dashboard_data.js·요약페이지를
                     재생성하고 구글시트에 업로드한다(merge job 전용).
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
    _creds.KEY_AUDIT_WEBHOOK:   os.environ.get("AUDIT_WEBHOOK_URL"),
}

_original_get = _creds.get


def _patched_get(key: str) -> str | None:
    if key in _env_map:
        return _env_map[key]
    return _original_get(key)


_creds.get = _patched_get

# ── config.yaml 준비 ─────────────────────────────────────────────────────
CONFIG_YAML = os.environ.get("CONFIG_YAML")
if CONFIG_YAML:
    cfg_path = Path("/tmp/config.yaml")
    cfg_path.write_text(CONFIG_YAML, encoding="utf-8")
else:
    cfg_path = Path(__file__).parent / "config.yaml"

if not cfg_path.exists():
    print("ERROR: config.yaml이 없습니다. CONFIG_YAML 환경변수를 설정하세요.")
    sys.exit(1)

# ── 실행 ─────────────────────────────────────────────────────────────────
from src.config import Config
from audit.collector import run_branch_audit
from audit.items import BRANCH_CUTOFFS

cfg = Config.load(cfg_path)
limit = int(os.environ.get("AUDIT_LIMIT", "0"))          # 지점당 N명 제한 (0=전체)
test_mode = os.environ.get("AUDIT_TEST", "").lower() == "true"  # 테스트: 저장·업로드·요약 전부 생략
branch_filter = os.environ.get("AUDIT_BRANCH", "").strip()      # 특정 지점만 (부분 일치)
skip_upload = os.environ.get("AUDIT_SKIP_UPLOAD", "").lower() == "true"  # 지점별 job: 시트 업로드 금지
merge_mode = os.environ.get("AUDIT_MERGE", "").lower() == "true"         # merge job: 스캔 없이 병합만

if test_mode and limit == 0:
    limit = 3  # 테스트 모드 기본: 3명만
if test_mode:
    print("🧪 테스트 모드 — 결과 저장/구글시트 업로드/요약페이지 갱신을 모두 생략합니다.", flush=True)

branches = cfg.branches
if branch_filter and branch_filter != "전체":
    branches = [b for b in branches if branch_filter in b.name]
    if not branches:
        print(f"ERROR: 지점 '{branch_filter}' 을 찾을 수 없습니다.")
        sys.exit(1)

failed = []

# ── merge 모드: 지점별 job 이 올려준 <지점>.json 을 모아 대시보드·요약페이지만 재생성 ──
# 케어포 접속·스캔을 하지 않는다. _write_dashboard_data() 가 dashboard_data.js 생성과
# 요약페이지(summary_page.generate) 재생성을 모두 담당하므로 단일 러너 때와 산출물이 같다.
if merge_mode:
    from audit.collector import AUDIT_DIR, _write_dashboard_data

    found = sorted(f.stem for f in AUDIT_DIR.glob("*.json")
                   if f.stem in {b.name for b in cfg.branches})
    print(f"병합 대상 지점 {len(found)}개: {', '.join(found) or '없음'}", flush=True)
    if not found:
        print("ERROR: 병합할 지점 결과가 없습니다 (아티팩트 다운로드·복호화 실패?).")
        sys.exit(1)
    _write_dashboard_data()
    print("대시보드 데이터·요약페이지 재생성 완료", flush=True)
    branches = []

for b in branches:
    cutoff = BRANCH_CUTOFFS.get(b.name, "2024.01.01")
    print(f"\n===== {b.name} 점검 시작 (기준일 {cutoff}) =====", flush=True)
    try:
        out = run_branch_audit(
            ctmnumb=b.ctmnumb,
            branch_name=b.name,
            cutoff=cutoff,
            limit=limit,
            headless=True,
            progress_cb=lambda m: print(m, flush=True),
            save=not test_mode,
        )
        ir = out["item_results"]
        # 공개 저장소 로그에 직원·수급자 이름이 남지 않도록 상태만 출력
        for no in sorted(ir, key=int):
            print(f"  항목 {no}: {ir[no]['status']}")
    except Exception as e:
        print(f"[{b.name}] 실패: {e}")
        failed.append(b.name)

# ── 구글시트 업로드 (테스트 모드·지점별 job 에서는 생략) ────────────────
# skip_upload: matrix 지점 job 은 자기 지점 결과만 갖고 있어 지금 올리면 시트의
# 다른 지점이 '수집전'으로 덮인다 → 업로드는 전 지점을 모은 merge job 에서만.
if not test_mode and not skip_upload:
    try:
        from audit.sheet_upload import upload
        upload()
    except Exception as e:
        print(f"구글시트 업로드 실패: {e}")
        failed.append("시트업로드")

if failed:
    print(f"\n일부 실패: {failed}")
    sys.exit(1)
if merge_mode:
    print("\n병합 완료")
else:
    print("\n🧪 테스트 성공 — 전 단계 정상 동작" if test_mode else "\n전체 점검 완료")
