# -*- coding: utf-8 -*-
"""정비 명세서(스캔 PDF) OCR → 타이어 사이즈·수리비 추출.

첨부 PDF는 정비소 영수증 스캔이라 텍스트 레이어가 없다(141개 전부).
다만 **자동차관리법 시행규칙 별지 제89호의2 표준서식**이라 항목이 고정 → OCR 신뢰도가 높다.
실측 검증(둔산 그랜드스타렉스 2026-03-18): 215/70R16 · 합계 448,000 · 소계 407,273 · VAT 40,727 전부 일치.

실행: py -X utf8 -m audit.ocr_car_invoice [지점키=청주] [--force]
결과: audit_results/정비이력_<지점>/index.json 에 ocr{} 필드 추가 (사이즈·합계·주행거리)

전제: tesseract + kor 언어데이터
  · winget install UB-Mannheim.TesseractOCR
  · kor.traineddata → C:\\Users\\alsgm\\tessdata (Program Files 는 관리자 권한 필요해 사용자 폴더 사용)

⚠️ OCR 은 한글을 글자마다 띄어 출력한다("합 계") → 매칭 전 **공백을 전부 제거**해야 한다.
⚠️ psm 6 은 이 서식에서 거의 실패한다. **psm 4**(다단 텍스트)를 쓸 것.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import fitz  # PyMuPDF — poppler 없이 PDF→이미지 렌더링

sys.stdout.reconfigure(encoding="utf-8")
RES = Path(__file__).resolve().parent.parent / "audit_results"
TESS = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
TESSDATA = r"C:\Users\alsgm\tessdata"

# 타이어 사이즈 표기가 정비소마다 다르다 — R 이 없는 경우가 있고(215/65 17),
# 공백 제거 후엔 215/6517 이 되므로 **R 을 선택**으로 둬야 둘 다 잡힌다.
#   실측: 215/70R16(명세서) · 195/65R15 · 215/65 17(타이어전문점 거래명세서)
# 표준 표기(한국타이어/콘티넨탈/KOTMA 확인): 폭(mm) / 편평비(%) [R=래디얼] 림(inch)
#   예 195/65R15 = 폭195mm · 편평비65% · 래디얼 · 15인치
# ⚠️ 정비소마다 표기가 제각각이라 슬래시·R 을 **둘 다 선택**으로 둬야 한다(실측):
#     215/70R16(슬래시+R) · 215/65 17(슬래시+공백) · 215 65 17(공백만) · TA21-175/50R15(품명에 붙음)
#   공백을 제거해 매칭하므로 '215 65 17' → '2156517' 이 된다.
# ★ 겹침 스캔(lookahead) 필수 — 비겹침 매칭이면 앞의 쓰레기 숫자가 정답을 삼킨다.
#   실측: '053|2156517|2143,000' 에서 053+21+56 을 먼저 먹어 뒤의 2156517(=215/65R17)을 놓쳤다.
# ★ [ZR0-9BA@]? — OCR 이 R 을 여러 글자로 오독한다(실측):
#     'TA21-175/50R15' → '175/50015'   (R→0)
#     '225/45R17,04,LH01' → '225/45817,04,LHO1'  (R→8)  ← 서구 아반떼1976
#   구조문자 자리를 넓게 열되, 실존규격 화이트리스트가 오탐을 막는다.
# 구분자 자리를 숫자까지 열면 '2156517'(=215/65R17) 에서 '1' 을 구분자로 먹고 림을 '72' 로
# 읽어버린다 → **구분자 없음 / 있음 두 해석을 모두 만들어** valid_size 로 거른다.
RE_SIZE_A = re.compile(r"(?=(\d{3}/?\d{2}\d{2}))")               # 구분자 없음: 2156517
RE_SIZE_B = re.compile(r"(?=(\d{3}/?\d{2}[ZR0-9BA@]\d{2}))")     # 구분자 있음: 225/45817

# 실존 단면폭(mm) — 195 는 있어도 200 은 없다. 5의 배수라고 다 규격이 아니다.
WIDTHS = {135, 145, 155, 165, 175, 185, 195, 205, 215, 225, 235, 245, 255,
          265, 275, 285, 295, 305, 315, 325, 335, 345, 355}
# 실존 편평비(%)
ASPECTS = {25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85}
RE_MONEY = re.compile(r"\d{1,3}(?:,\d{3})+")
RE_KM = re.compile(r"주행거리[^0-9]{0,10}([\d,]{3,})")
# ⚠️ 서식이 2종이다 — 명세서(별지 89호의2)는 '합계', 견적서(별지 89호의3)는 '총액'.
#    게다가 표 레이아웃이라 라벨 뒤 첫 숫자가 총액이 아닌 경우가 많다(견적서: 총액→일반→530,000).
#    → 금액 중 **최댓값(주행거리 제외)**을 총액으로 본다. 총액은 부가세 포함이라 항상 최대.
#      실측: 명세서 448,000(=합계) · 견적서 583,000(=총액) 둘 다 정확.
RE_FORM_EST = re.compile(r"견적서|89호의3")
RE_FORM_BILL = re.compile(r"명세서|89호의2")


def ocr_pdf(pdf: Path, dpi: int = 300) -> tuple[str, int]:
    """PDF/이미지 첨부 OCR → (공백 제거 텍스트, 페이지수).
    첨부는 PDF 뿐 아니라 **JPG 도 있다**(서구·천안은 사진으로 올린다) → 둘 다 처리."""
    env = dict(os.environ, TESSDATA_PREFIX=TESSDATA)
    out = []
    if pdf.suffix.lower() in (".jpg", ".jpeg", ".png"):
        r = subprocess.run([TESS, str(pdf), "stdout", "-l", "kor+eng", "--psm", "4"],
                           capture_output=True, env=env, timeout=180)
        return re.sub(r"\s+", "", r.stdout.decode("utf-8", "ignore")), 1
    doc = fitz.open(pdf)
    for i in range(doc.page_count):
        png = pdf.with_suffix(f".p{i}.tmp.png")
        try:
            doc[i].get_pixmap(dpi=dpi).save(png)
            r = subprocess.run([TESS, str(png), "stdout", "-l", "kor+eng", "--psm", "4"],
                               capture_output=True, env=env, timeout=120)
            out.append(r.stdout.decode("utf-8", "ignore"))
        except Exception as e:
            out.append("")
        finally:
            png.unlink(missing_ok=True)
    npages = doc.page_count
    doc.close()
    return re.sub(r"\s+", "", " ".join(out)), npages


RE_INS = re.compile(r"보험사[:\s]*[가-힣A-Za-z]{2,6}|보험\)?수리|자차")

def valid_size(t: str) -> bool:
    """타이어 규격 유효성 검사. 슬래시·R 을 선택으로 풀면 아무 숫자열이나 걸리므로 필수.

    규칙(온라인 표준 확인 2026-07-17):
      · 폭 135~355mm 이고 **5의 배수** (155/165/175/185/195/205/215/225...)
      · 편평비 25~85% 이고 **5의 배수** (30/35/40/45/50/55/60/65/70/75/80)
      · 림 12~22 inch
    실측 오독 예: 122/1269 · 800/8835 · 175/5001 · 165/6081 · 195/6581 → 전부 걸러짐.
    """
    m = re.fullmatch(r"(\d{3})/?(\d{2})[ZR0-9BA@]?(\d{2})", t)
    if not m:
        return False
    w, a, r = int(m.group(1)), int(m.group(2)), int(m.group(3))
    # 실존 규격만 통과시킨다. 5의 배수 규칙만으론 오독을 못 거른다 —
    # 실측 오탐: 200/60R18(폭 200 은 실존 안함) · 260/65R14(폭260에 14인치 조합 없음)
    if w not in WIDTHS or a not in ASPECTS or not (12 <= r <= 22):
        return False
    # 폭이 클수록 큰 림을 쓴다 — 좁은 타이어에 큰 림, 넓은 타이어에 작은 림 조합은 없다
    if w <= 175 and r > 17:
        return False
    if w >= 245 and r < 15:
        return False
    return True


def norm_size(t: str) -> str:
    """표기 흔들림을 표준형(195/65R15)으로 통일 — '2156517' → '215/65R17'."""
    m = re.fullmatch(r"(\d{3})/?(\d{2})[ZR0-9BA@]?(\d{2})", t)
    return f"{m.group(1)}/{m.group(2)}R{m.group(3)}" if m else t


def find_sizes(text: str) -> list[str]:
    """텍스트에서 유효한 타이어 규격만 표준형으로 뽑는다.
    ★ 사이즈 탐색은 **반드시 이 함수 하나만** 쓸 것 — OCR 원문과 케어포 정비내역 텍스트
      양쪽에서 찾아야 하는데, 규칙을 복사해두면 한쪽만 고쳐져 조용히 어긋난다(실제로 겪음)."""
    flat = (text or "").replace(" ", "")
    cand = [m.group(1) for m in RE_SIZE_A.finditer(flat)]          + [m.group(1) for m in RE_SIZE_B.finditer(flat)]   # lookahead 라 group(1)
    return list(dict.fromkeys(norm_size(t) for t in cand if valid_size(t)))


def parse(flat: str, pages: int = 1) -> dict:
    sizes = find_sizes(flat)
    km = RE_KM.search(flat)
    kmv = km.group(1) if km else None
    monies = [m for m in RE_MONEY.findall(flat) if m != kmv]   # 주행거리는 금액 아님
    vals = sorted({int(m.replace(",", "")) for m in monies}, reverse=True)
    form = "견적서" if RE_FORM_EST.search(flat) else ("명세서" if RE_FORM_BILL.search(flat) else "")
    return {
        "form": form,
        "pages": pages,
        # 보험수리는 총액이 보험사 부담이라 지점 수리비가 아닐 수 있음 → 경고만 달고 값은 그대로 둔다
        "insurance": bool(RE_INS.search(flat)),
        "size": sizes[0] if sizes else "",
        "sizes_all": sizes,
        "total": vals[0] if vals else None,          # 최댓값 = 부가세 포함 총액
        "amounts": vals[:6],                          # 검증용 상위 금액들
        "km": kmv or "",
        "ok": bool(vals or sizes),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("branch", nargs="?", default="청주")
    ap.add_argument("--force", action="store_true", help="이미 OCR된 것도 다시")
    args = ap.parse_args()

    if not Path(TESS).exists():
        print(f"tesseract 없음: {TESS}")
        sys.exit(1)

    src = next((d for d in RES.glob("정비이력_*") if args.branch in d.name), None)
    if not src:
        print(f"수집물 없음. 먼저: py -X utf8 -m audit.collect_car_maintenance {args.branch}")
        sys.exit(1)
    idx = src / "index.json"
    data = json.loads(idx.read_text(encoding="utf-8"))

    todo = [r for r in data["records"] if r.get("files") and (args.force or not r.get("ocr"))]
    print(f"{data['branch']} — OCR 대상 {len(todo)}건", flush=True)
    t0, n_ok = time.time(), 0
    for i, r in enumerate(todo, 1):
        # ⚠️ **첨부 전부** 를 읽어 이어붙인다. 예전엔 files[0] 만 읽었는데,
        #    첫 파일이 명세서가 아니면(점검 사진 등) 그 건은 영영 '금액 없음'이 됐다.
        #    실측: 서구 아반떼2768 2025.11.12 는 첨부 10개, 둔산 그랜드스타렉스 2025.05.20 은
        #    files[0] 이 '9869 정기점검1.jpg'(사진)이라 나머지 3개 속 명세서를 못 읽었다.
        parts, npages = [], 0
        for fn in (r.get("files") or []):
            p = src / (r.get("dir") or r["car"]) / fn   # dir = 첨부 실제 폴더(동명 차량 분리)
            if not p.exists():
                continue
            f, n = ocr_pdf(p)
            parts.append(f)
            npages += n
        if not parts:
            continue
        flat = "".join(parts)
        r["ocr"] = parse(flat, npages)
        r["ocr_raw"] = flat          # 파싱 규칙이 바뀌어도 재OCR 없이 재파싱하려고 원문 보관
        if r["ocr"]["ok"]:
            n_ok += 1
        tag = f"사이즈 {r['ocr']['size']}" if r["ocr"]["size"] else ""
        if r["ocr"]["pages"] > 1: tag += f" [{r['ocr']['pages']}p]"
        if r["ocr"]["insurance"]: tag += " [보험]"
        amt = f"{r['ocr']['total']:,}원" if r["ocr"]["total"] else "합계 못읽음"
        print(f"  [{i}/{len(todo)}] {r['car'][:12]:<12} {r['date']} {amt:>12} {tag}", flush=True)

    idx.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n완료: {n_ok}/{len(todo)}건 추출 ({time.time()-t0:.0f}초) → {idx}", flush=True)


if __name__ == "__main__":
    main()
