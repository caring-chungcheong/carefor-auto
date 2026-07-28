"""
출석 현황 이미지 생성 (Pillow).

레이아웃:
  ┌──────────────────────────────────────┐
  │ 지점별 출석 현황       26.06.22(월)  │
  ├──────────┬──────────┬────┬────┬──────┤
  │ 지점명   │현원(수급)│결석│출석│총인원│  ← 하늘색 헤더
  ├──────────┼──────────┼────┼────┼──────┤
  │ 둔산점   │    69    │  0 │ 65 │  80  │
  │ 서구점   │    79    │  3 │ 71 │  80  │  ← 흰/연파 교차
  │ 천안점   │    64    │  2 │ 50 │  70  │
  │청주오창점│    50    │  3 │ 47 │  60  │
  └──────────┴──────────┴────┴────┴──────┘
"""
from __future__ import annotations

import io
from datetime import date

from PIL import Image, ImageDraw, ImageFont

import os, sys

def _find_font(bold: bool) -> str:
    # Windows
    win_path = f"C:/Windows/Fonts/{'malgunbd' if bold else 'malgun'}.ttf"
    if os.path.exists(win_path):
        return win_path
    # Linux (GitHub Actions) — 나눔고딕
    candidates = [
        f"/usr/share/fonts/truetype/nanum/NanumGothic{'Bold' if bold else ''}.ttf",
        f"/usr/share/fonts/truetype/nanum/NanumGothic{'ExtraBold' if bold else ''}.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    raise FileNotFoundError("한글 폰트를 찾을 수 없습니다")

# 색상
_BG          = "#FFFFFF"
_HDR_BG      = "#5BA4CF"   # 하늘색
_HDR_TEXT    = "#FFFFFF"
_ROW_EVEN    = "#FFFFFF"
_ROW_ODD     = "#EBF5FB"   # 연한 하늘색
_BORDER      = "#B8D9F0"
_TEXT_DARK   = "#1A1A2E"
_TEXT_GRAY   = "#555577"
_TITLE_TEXT  = "#1A1A2E"
_DATE_TEXT   = "#4A4A6A"
_ACCENT      = "#3A7EBD"   # 제목 하단 선
_CAP_BG      = "#FFE066"   # 총인원 열 노란색 배경
_SUM_BG      = "#D6EAF8"   # 합계 행 배경 (연한 파랑)


def _font(bold: bool, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(_find_font(bold), size)


def _text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int]:
    bb = draw.textbbox((0, 0), text, font=font)
    return bb[2] - bb[0], bb[3] - bb[1]


def _draw_cell_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    x: int, y: int, w: int, h: int,
    color: str,
    align: str = "center",   # "center" | "left"
) -> None:
    tw, th = _text_size(draw, text, font)
    ty = y + (h - th) // 2
    if align == "center":
        tx = x + (w - tw) // 2
    else:
        tx = x + 14
    draw.text((tx, ty), text, font=font, fill=color)


def _fmt_avg(v) -> str | None:
    """월평균 값 → 'XX.XX' 문자열. 없음/'-'/빈값/0 이면 None.

    ★0 은 '수집 실패'다 — 케어포 화면에서 못 읽으면 0.0 으로 오는데, 그걸 '0.00'으로 찍으면
      진짜 값처럼 보인다. 실제로 휴관이라 0명인 달은 없으므로 0 은 미표기('-')로 둔다.
    """
    if v in (None, "-", "") or v == 0:
        return None
    try:
        return f"{float(v):.2f}"
    except (TypeError, ValueError):
        return None


def _draw_avg_cell(draw, cur, prev, f_num, f_small, x, ry, cw, h,
                   dark="#1A1A2E", gray="#555577") -> None:
    """월평균 입소자 칸: 현월(큰 글씨) + 그 아래 '(전월 XX.XX)'(작은 회색). 전월 없으면 현월만 가운데."""
    cur_s = _fmt_avg(cur) or "-"
    prev_s = _fmt_avg(prev)
    cw_i, ch = _text_size(draw, cur_s, f_num)
    if prev_s is None:
        draw.text((x + (cw - cw_i) // 2, ry + (h - ch) // 2), cur_s, font=f_num, fill=dark)
        return
    ptxt = f"(전월 {prev_s})"
    pw, ph = _text_size(draw, ptxt, f_small)
    gap = 10   # 현월 값과 '(전월 …)' 사이 간격
    total = ch + gap + ph
    ty0 = ry + (h - total) // 2
    draw.text((x + (cw - cw_i) // 2, ty0), cur_s, font=f_num, fill=dark)
    draw.text((x + (cw - pw) // 2, ty0 + ch + gap), ptxt, font=f_small, fill=gray)


def generate_image(target_date: date, branches_data: list[dict]) -> bytes:
    """출석 현황 표 PNG를 생성해 bytes로 반환."""

    W          = 880
    SIDE       = 24
    TABLE_W    = W - 2 * SIDE
    TITLE_H    = 88
    HDR_H      = 60
    ROW_H      = 54
    BOTTOM_PAD = 28

    n = len(branches_data)
    SUM_ROW_H  = 56
    H = TITLE_H + HDR_H + ROW_H * n + SUM_ROW_H + BOTTOM_PAD

    # 컬럼 정의: (헤더 텍스트, 너비, 정렬)
    # TABLE_W = 772 → 합이 맞아야 함
    cols = [
        ("지점명",        155, "center"),
        ("현원\n(수급중)", 148, "center"),
        ("결석",          107, "center"),
        ("출석",          107, "center"),
        ("정원",          135, "center"),
        ("월평균\n입소자", 180, "center"),
    ]
    assert sum(c[1] for c in cols) == TABLE_W, f"col sum={sum(c[1] for c in cols)} != {TABLE_W}"

    img  = Image.new("RGB", (W, H), _BG)
    draw = ImageDraw.Draw(img)

    f_title = _font(True,  30)
    f_date  = _font(True,  19)
    f_hdr   = _font(True,  16)
    f_name  = _font(True,  17)
    f_num   = _font(False, 17)
    f_small = _font(False, 13)   # 월평균 아래 '(전월 XX.XX)' 회색 보조값

    # ── 제목 영역 ─────────────────────────────────────
    title_text = "지점별 출석 현황"
    tw, _ = _text_size(draw, title_text, f_title)
    draw.text(((W - tw) // 2, 22), title_text, font=f_title, fill=_TITLE_TEXT)

    weekday_kr = ["월", "화", "수", "목", "금", "토", "일"][target_date.weekday()]
    date_str   = f"{target_date.strftime('%y.%m.%d')}({weekday_kr}요일)"
    dw, _      = _text_size(draw, date_str, f_date)
    draw.text((W - SIDE - dw, 30), date_str, font=f_date, fill=_DATE_TEXT)

    # 제목 하단 강조선
    line_y = TITLE_H - 10
    draw.line([(SIDE, line_y), (W - SIDE, line_y)], fill=_ACCENT, width=2)

    # ── 헤더 행 ───────────────────────────────────────
    hy = TITLE_H
    draw.rectangle([SIDE, hy, W - SIDE, hy + HDR_H], fill=_HDR_BG)

    x = SIDE
    for label, cw, align in cols:
        lines = label.split("\n")
        if len(lines) == 2:
            lh = _text_size(draw, lines[0], f_hdr)[1]
            total = lh * 2 + 3
            ty0   = hy + (HDR_H - total) // 2
            for k, ln in enumerate(lines):
                lw, _ = _text_size(draw, ln, f_hdr)
                draw.text((x + (cw - lw) // 2, ty0 + k * (lh + 3)), ln, font=f_hdr, fill=_HDR_TEXT)
        else:
            _draw_cell_text(draw, label, f_hdr, x, hy, cw, HDR_H, _HDR_TEXT, "center")
        x += cw

    # ── 데이터 행 ─────────────────────────────────────
    keys = ["name", "hyeon_won", "gyeol_seok", "chul_seok", "capacity", "avg_attendees"]

    cap_x   = SIDE + sum(c[1] for c in cols[:3])   # 출석 열 시작 x
    cap_end = cap_x + cols[3][1]                    # 출석 열 끝 x

    for i, b in enumerate(branches_data):
        ry     = TITLE_H + HDR_H + i * ROW_H
        row_bg = _ROW_EVEN if i % 2 == 0 else _ROW_ODD
        draw.rectangle([SIDE, ry, W - SIDE, ry + ROW_H], fill=row_bg)
        # 출석 열만 노란색 배경
        draw.rectangle([cap_x, ry, cap_end, ry + ROW_H], fill=_CAP_BG)

        x = SIDE
        for j, (_, cw, align) in enumerate(cols):
            if j == 5:
                _draw_avg_cell(draw, b.get("avg_attendees", "-"), b.get("prev_avg_attendees"),
                               f_num, f_small, x, ry, cw, ROW_H)
                x += cw
                continue
            raw = b.get(keys[j], "-")
            val = str(raw)
            font = f_name if j == 0 else f_num
            _draw_cell_text(draw, val, font, x, ry, cw, ROW_H, _TEXT_DARK, align)
            x += cw

    # ── 합계 행 ───────────────────────────────────────
    sy = TITLE_H + HDR_H + n * ROW_H
    draw.rectangle([SIDE, sy, W - SIDE, sy + SUM_ROW_H], fill=_SUM_BG)
    draw.rectangle([cap_x, sy, cap_end, sy + SUM_ROW_H], fill=_CAP_BG)  # 출석 열 노란색

    prev_vals = [float(_fmt_avg(b.get("prev_avg_attendees"))) for b in branches_data
                 if _fmt_avg(b.get("prev_avg_attendees")) is not None]
    totals = {
        "hyeon_won":  sum(b["hyeon_won"]  for b in branches_data),
        "gyeol_seok": sum(b["gyeol_seok"] for b in branches_data),
        "chul_seok":  sum(b["chul_seok"]  for b in branches_data),
        "avg_attendees": round(
            sum(b.get("avg_attendees", 0) for b in branches_data) / len(branches_data), 1
        ) if branches_data else 0.0,
        "prev_avg_attendees": round(sum(prev_vals) / len(prev_vals), 2) if prev_vals else None,
    }
    sum_vals = [
        "합계",
        str(totals["hyeon_won"]),
        str(totals["gyeol_seok"]),
        str(totals["chul_seok"]),
        str(totals["hyeon_won"]),
        None,   # 월평균은 아래에서 스택 렌더
    ]

    x = SIDE
    for j, (_, cw, align) in enumerate(cols):
        if j == 5:
            _draw_avg_cell(draw, totals["avg_attendees"], totals["prev_avg_attendees"],
                           f_num, f_small, x, sy, cw, SUM_ROW_H)
            x += cw
            continue
        font = f_hdr if j == 0 else f_num
        _draw_cell_text(draw, sum_vals[j], font, x, sy, cw, SUM_ROW_H, _TEXT_DARK, align)
        x += cw

    # ── 격자선 ────────────────────────────────────────
    table_top    = TITLE_H
    table_bottom = TITLE_H + HDR_H + n * ROW_H + SUM_ROW_H

    # 가로선 (데이터 행 구분)
    for i in range(n + 1):
        ly = TITLE_H + HDR_H + i * ROW_H
        draw.line([(SIDE, ly), (W - SIDE, ly)], fill=_BORDER, width=1)
    # 합계 행 하단선
    draw.line([(SIDE, sy + SUM_ROW_H), (W - SIDE, sy + SUM_ROW_H)], fill=_BORDER, width=1)

    # 테이블 외곽선
    draw.rectangle([SIDE, table_top, W - SIDE, table_bottom], outline=_BORDER, width=2)

    # 세로선 (열 구분)
    sep_chul = SIDE + sum(c[1] for c in cols[:4])   # 출석 | 정원
    sep_cap  = SIDE + sum(c[1] for c in cols[:5])   # 정원 | 월평균
    x = SIDE
    for _, cw, _ in cols[:-1]:
        x += cw
        if x == sep_chul:
            lw = 5   # 출석↔정원 넓은 구분
        elif x == sep_cap:
            lw = 3   # 정원↔월평균 기존 유지
        else:
            lw = 1
        draw.line([(x, table_top), (x, table_bottom)], fill=_BORDER, width=lw)

    buf = io.BytesIO()
    img.save(buf, format="PNG", dpi=(144, 144))
    return buf.getvalue()
