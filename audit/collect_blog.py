# -*- coding: utf-8 -*-
"""지점 케어링 네이버 블로그(RSS)에서 월간 3종(식단표·프로그램표·가정통신문) 전월 게시 여부 자동 확인.

17③(월간 계획표·식단표·소식 월1회 제공) 자동 판정용.
네이버 블로그는 WebFetch로는 막히지만 RSS(rss.blog.naver.com/<id>.xml)는 Playwright로 정상 수신됨.
'전월 등록' 판정(사용자 확정 2026-07-20): 각 유형 최신 게시일이 전월 1일 이후면 월1회 유지 → 게시 O.
일일 '오늘의 프로그램'은 월간 프로그램표와 구분(제외)한다.
"""
import re
from datetime import datetime

TYPES = ("식단표", "프로그램표", "가정통신문")
_MON = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def _pdate(s):
    m = re.search(r"(\d{1,2})\s+(\w{3})\s+(\d{4})", s or "")
    return datetime(int(m.group(3)), _MON.get(m.group(2), 1), int(m.group(1))) if m else None


def _classify(cat, title):
    s = cat + " " + title
    if "가정통신" in s:
        return "가정통신문"
    if "식단" in s:
        return "식단표"
    # 월간 프로그램(일정표/계획) — 일일 '오늘의 프로그램'은 제외
    if "프로그램" in s and any(k in s for k in ("일정표", "월간", "계획")) and "오늘의" not in s:
        return "프로그램표"
    return None


def check_blog(page, blog_id, ref_year, ref_month, progress=print) -> dict:
    """RSS 스캔 → 유형별 최신 게시일 + 전월(ref_year/ref_month) 1일 이후 게시 여부.

    반환: {'식단표': {'date','title','ok'}, '프로그램표': {...}, '가정통신문': {...},
           'all_ok': bool, 'blog_id': id, 'error': 있으면}
    """
    result = {t: {"date": None, "title": "", "ok": False} for t in TYPES}
    if not blog_id:
        return {**result, "all_ok": False, "blog_id": None, "error": "블로그 미등록"}
    # CARING_BLOG 값은 전체 URL일 수 있음 → 블로그 ID만 추출(rss.blog.naver.com/<id>.xml)
    blog_id = blog_id.rstrip("/").split("/")[-1].split("?")[0]
    # 네이버 RSS는 비브라우저 요청·HeadlessChrome 기본 UA엔 빈 응답을 주므로,
    # 실제 UA를 지정한 별도 컨텍스트(케어포 페이지와 분리)에서 실브라우저로 받고 innerText 폴링.
    url = f"https://rss.blog.naver.com/{blog_id}.xml"
    xml = ""
    ctx = None
    try:
        ctx = page.context.browser.new_context(
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"))
        bp = ctx.new_page()
        for attempt in range(3):   # 일시적 빈응답(레이트리밋) 대비 재시도
            bp.goto(url, wait_until="domcontentloaded", timeout=25000)
            for _ in range(12):
                bp.wait_for_timeout(500)
                xml = bp.evaluate("()=>document.body?document.body.innerText:''") or ""
                if "<item>" in xml:
                    break
            if "<item>" not in xml:
                xml = bp.content()
            if "<item>" in xml:
                break
            bp.wait_for_timeout(2500)   # 재시도 전 대기
    except Exception as e:
        return {**result, "all_ok": False, "blog_id": blog_id, "error": f"RSS 수신 실패: {e}"}
    finally:
        if ctx:
            try:
                ctx.close()
            except Exception:
                pass
    if "<item>" not in (xml or ""):
        return {**result, "all_ok": False, "blog_id": blog_id, "error": "RSS 항목 없음/비공개(레이트리밋?)"}

    cutoff = datetime(ref_year, ref_month, 1)   # 전월 1일 이후면 월1회 유지로 인정
    for it in re.findall(r"<item>(.*?)</item>", xml, re.S):
        def _f(tag):
            m = re.search(rf"<{tag}>(.*?)</{tag}>", it, re.S)
            return re.sub(r"<!\[CDATA\[|\]\]>|<.*?>", "", m.group(1)).strip() if m else ""
        title, cat = _f("title"), _f("category")
        d = _pdate(_f("pubDate"))
        k = _classify(cat, title)
        if k and d and (result[k]["date"] is None or d > datetime.strptime(result[k]["date"], "%Y-%m-%d")):
            result[k] = {"date": d.strftime("%Y-%m-%d"), "title": title[:40], "ok": d >= cutoff}
    result["all_ok"] = all(result[t]["ok"] for t in TYPES)
    result["blog_id"] = blog_id
    progress(f"    블로그 {blog_id}: " + ", ".join(
        f"{t}={'O' if result[t]['ok'] else 'X'}({result[t]['date'] or '없음'})" for t in TYPES))
    return result
