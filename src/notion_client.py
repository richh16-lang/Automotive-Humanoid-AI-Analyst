"""Notion API를 통해 분석 결과를 DB 페이지로 저장합니다."""
import logging
import os
import re
import requests as _requests
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))

from notion_client import Client
from notion_client.errors import APIResponseError

logger = logging.getLogger(__name__)

_MAX_BLOCK_TEXT = 1900   # Notion 블록 하나당 최대 글자 수 (한도 2000)
_NOTION_VERSION = "2022-06-28"


# ══════════════════════════════════════════════════════════════════════════════
# 내부 유틸
# ══════════════════════════════════════════════════════════════════════════════

def _get_client() -> Client:
    token = os.environ.get("NOTION_TOKEN", "")
    if not token:
        raise ValueError("NOTION_TOKEN 환경변수가 없습니다.")
    return Client(auth=token)


def _notion_query(db_id: str,
                  filter_body: dict | None = None,
                  sorts: list | None = None,
                  page_size: int = 10) -> list[dict]:
    """
    requests로 Notion DB를 직접 쿼리.
    notion-client SDK의 databases.query() 버전 호환 문제를 우회.
    """
    token = os.environ.get("NOTION_TOKEN", "")
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": _NOTION_VERSION,
        "Content-Type": "application/json",
    }
    body: dict = {"page_size": page_size}
    if filter_body:
        body["filter"] = filter_body
    if sorts:
        body["sorts"] = sorts

    resp = _requests.post(
        f"https://api.notion.com/v1/databases/{db_id}/query",
        headers=headers,
        json=body,
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json().get("results", [])


def _rich_text(content: str) -> list[dict]:
    """Notion rich_text 포맷. 2000자 초과 시 자름."""
    return [{"type": "text", "text": {"content": content[:2000]}}]


def _rich_text_with_links(text: str) -> list[dict]:
    """
    URL 패턴을 '[Link]' 하이퍼링크로 변환한 Notion rich_text.
    [출처: URL] / [링크: URL] 패턴과 단독 URL 모두 처리.
    """
    URL_PAT = re.compile(
        r'\[(?:출처|링크|Source|참조|source)[:\s]*(https?://[^\]]+)\]'
        r'|(https?://\S{15,})'
    )
    result: list[dict] = []
    last = 0
    for m in URL_PAT.finditer(text):
        url    = (m.group(1) or m.group(2) or "").strip()
        before = text[last:m.start()].strip()
        if before:
            result.append({"type": "text", "text": {"content": before + " "}})
        if url:
            result.append({
                "type": "text",
                "text": {"content": "[Link]", "link": {"url": url}},
                "annotations": {"color": "blue", "underline": True},
            })
        result.append({"type": "text", "text": {"content": " "}})
        last = m.end()
    tail = text[last:].strip()
    if tail:
        result.append({"type": "text", "text": {"content": tail[:1900]}})
    return result or [{"type": "text", "text": {"content": text[:2000]}}]


def _extract_summary_text(analysis: dict) -> str:
    """핵심 요약 섹션에서 첫 3개 불릿 추출 → 요약 컬럼용."""
    sections = analysis.get("sections", {})
    for title, content in sections.items():
        if any(k in title for k in ("핵심 요약", "요약", "Summary")):
            bullets = []
            for line in content.split("\n"):
                s = line.strip().lstrip("-•·▪▸*").strip()
                s = re.sub(r"\[(?:출처|링크)[:\s]*https?://[^\]]+\]", "", s).strip()
                s = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", s)
                if s:
                    bullets.append(s[:200])
                if len(bullets) >= 3:
                    break
            return " | ".join(bullets)
    return ""


def _paragraph_blocks(text: str) -> list[dict]:
    """
    긴 텍스트를 여러 paragraph 블록으로 분할.

    1900자 고정 분할 → 단어·줄 경계 우선 분할로 교체.
    "분산형"이 "분" + "산형"으로 잘리는 현상 방지.
    """
    if not text or not text.strip():
        return []

    chunks: list[str] = []
    remaining = text
    while len(remaining) > _MAX_BLOCK_TEXT:
        # 1) 1900자 이내 마지막 줄바꿈 위치
        cut = remaining.rfind("\n", 0, _MAX_BLOCK_TEXT)
        if cut <= 0:
            # 2) 줄바꿈 없으면 마지막 공백
            cut = remaining.rfind(" ", 0, _MAX_BLOCK_TEXT)
        if cut <= 0:
            # 3) 공백도 없으면 강제 분할
            cut = _MAX_BLOCK_TEXT
        chunks.append(remaining[:cut])
        remaining = remaining[cut:].lstrip("\n")

    if remaining.strip():
        chunks.append(remaining)

    return [
        {"object": "block", "type": "paragraph",
         "paragraph": {"rich_text": _rich_text(c)}}
        for c in chunks
    ]


def _heading_block(text: str) -> dict:
    return {
        "object": "block", "type": "heading_2",
        "heading_2": {"rich_text": _rich_text(text[:100])},
    }


def _divider_block() -> dict:
    return {"object": "block", "type": "divider", "divider": {}}


def _callout_block(text: str, emoji: str = "📌") -> dict:
    return {
        "object": "block", "type": "callout",
        "callout": {
            "icon": {"type": "emoji", "emoji": emoji},
            "rich_text": _rich_text(text[:2000]),
        },
    }


def _safe_kw_list(keywords: list) -> list[dict]:
    """multi_select용 키워드 목록 — 특수문자·길이 제한 처리."""
    result = []
    for kw in keywords[:5]:
        name = str(kw)[:99].replace(",", " ")   # Notion 쉼표 불가
        if name.strip():
            result.append({"name": name})
    return result


def _image_block(url: str) -> dict:
    """외부 URL 이미지 블록 (QuickChart.io 등)."""
    return {
        "object": "block",
        "type": "image",
        "image": {"type": "external", "external": {"url": url}},
    }


def _table_block(rows: list[list[str]], has_header: bool = True) -> dict:
    """Notion 테이블 블록 생성."""
    width = max(len(r) for r in rows) if rows else 2
    children = []
    for row in rows:
        cells = []
        for cell_text in row:
            cells.append([{"type": "text", "text": {"content": str(cell_text)[:2000]}}])
        # 열 수 맞추기
        while len(cells) < width:
            cells.append([{"type": "text", "text": {"content": ""}}])
        children.append({
            "object": "block",
            "type": "table_row",
            "table_row": {"cells": cells},
        })
    return {
        "object": "block",
        "type": "table",
        "table": {
            "table_width":      width,
            "has_column_header": has_header,
            "has_row_header":    False,
            "children":          children,
        },
    }


def _bullet_block(text: str) -> dict:
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": _rich_text(text[:2000])},
    }


def _build_blocks(analysis: dict) -> list[dict]:
    """분석 결과 dict → Notion 블록 목록 (이미지·테이블 포함)."""
    from .chart_generator import (
        keyword_chart_url,
        source_chart_url,
        workload_chart_url,
    )

    blocks: list[dict] = []
    provider = analysis.get("provider") or analysis.get("model", "-")
    attribution = analysis.get("model_attribution", provider)
    keywords = analysis.get("keywords_found", [])
    sources  = analysis.get("sources", [])

    # ── 메타 callout ──────────────────────────────────────────
    meta = (
        f"📅 날짜: {analysis.get('date', '-')}  |  "
        f"🤖 AI: {attribution}  |  "
        f"📰 수집 기사: {analysis.get('article_count', 0)}건\n"
        f"🏷 키워드: {', '.join(keywords[:10])}\n"
        f"📡 출처: {', '.join(sources[:8])}"
    )
    blocks.append(_callout_block(meta, "📊"))
    blocks.append(_divider_block())

    # ── 주요 지표 테이블 ──────────────────────────────────────
    blocks.append(_callout_block("📈 주요 분석 지표", "📈"))
    metric_rows = [
        ["항목",      "내용"],
        ["분석 일자",  analysis.get("date", "-")],
        ["수집 기사",  f"{analysis.get('article_count', 0)}건"],
        ["핵심 키워드", ", ".join(keywords[:8])],
        ["데이터 출처", ", ".join(sources[:6])],
        ["AI 기여",    attribution],
    ]
    blocks.append(_table_block(metric_rows, has_header=True))
    blocks.append(_divider_block())

    # ── 키워드 차트 이미지 ────────────────────────────────────
    kw_url = keyword_chart_url(keywords)
    if kw_url:
        blocks.append(_callout_block("핵심 키워드 우선순위", "🔑"))
        blocks.append(_image_block(kw_url))

    # ── 출처 분포 차트 이미지 ─────────────────────────────────
    src_url = source_chart_url(sources)
    if src_url:
        blocks.append(_callout_block("데이터 출처 분포", "📡"))
        blocks.append(_image_block(src_url))

    blocks.append(_divider_block())

    # ── 10개 섹션 ─────────────────────────────────────────────
    sections: dict = analysis.get("sections", {})
    if sections:
        for idx, (title, content) in enumerate(sections.items()):
            if title.strip():
                blocks.append(_heading_block(title))

            # 스토리지 워크로드 섹션에 차트 추가
            if "워크로드" in title or "Workload" in title or "스토리지" in title:
                wl_url = workload_chart_url()
                if wl_url:
                    blocks.append(_image_block(wl_url))

            if content.strip():
                is_summary = any(k in title for k in ("핵심 요약", "요약", "Summary"))
                # ── 마크다운 표는 paragraph 블록으로 그대로 저장 ──────────────
                # Notion 네이티브 table 블록으로 변환하면 _extract_page_text()
                # 가 table_row 자식을 읽지 못해 대시보드 캐시 로드 시 표가
                # 통째로 유실됨. paragraph로 저장하면 마크다운 텍스트가 보존되어
                # _md_to_html()이 HTML 표로 정상 변환.
                bullets = _parse_bullets(content, keep_links=is_summary)
                if bullets:
                    for b in bullets:
                        if isinstance(b, list):  # rich_text with links
                            blocks.append({
                                "object": "block",
                                "type": "bulleted_list_item",
                                "bulleted_list_item": {"rich_text": b},
                            })
                        else:
                            blocks.append(_bullet_block(b))
                else:
                    blocks.extend(_paragraph_blocks(content))

            blocks.append(_divider_block())
    else:
        # 섹션 파싱 실패 → raw 전체 삽입
        raw = analysis.get("raw", "")
        logger.warning("섹션 파싱 결과 없음, raw 텍스트 삽입 (%d자)", len(raw))
        blocks.extend(_paragraph_blocks(raw))

    # ── 참조 URL 목록 ─────────────────────────────────────────────────────
    # 형식: ● [기사 제목]  [Link](URL)
    # 제목이 없거나 도메인형이면 BeautifulSoup으로 스크래핑
    source_items = analysis.get("source_items", [])
    source_urls  = analysis.get("source_urls", [])
    if source_items or source_urls:
        blocks.append(_heading_block("📚 참조 URL"))

        fetch_count = 0          # 네트워크 타이틀 조회 횟수 제한
        _MAX_FETCHES = 8         # 최대 8건 스크래핑 (저장 속도 보호)

        items_to_render: list[tuple[str, str]] = []   # (title, url)
        if source_items:
            for item in source_items[:20]:
                t = (item.get("title") or "").strip()
                u = (item.get("url")   or "").strip()
                if u:
                    items_to_render.append((t, u))
        else:
            for u in source_urls[:20]:
                if u:
                    items_to_render.append(("", u))

        for title, url in items_to_render:
            # 타이틀 스크래핑 필요 여부 확인
            if fetch_count < _MAX_FETCHES and _notion_needs_title(title, url):
                fetched = _fetch_notion_title(url)
                if fetched:
                    title = fetched
                fetch_count += 1
            elif _notion_needs_title(title, url):
                # 스크래핑 횟수 초과 시 도메인 fallback
                try:
                    from urllib.parse import urlparse as _up
                    title = _up(url).netloc.replace("www.", "") or url[:60]
                except Exception:
                    title = url[:60]

            blocks.append(_source_item_bullet(title, url))

    return blocks


def _parse_md_table_rows(table_text: str) -> list[list[str]]:
    """
    마크다운 테이블 텍스트 → 행/열 리스트.
    구분선(|---|---|)은 제외하고 헤더+데이터 행만 반환.
    """
    rows: list[list[str]] = []
    for line in table_text.split("\n"):
        stripped = line.strip()
        if not (stripped.startswith("|") and stripped.endswith("|")):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        # 구분선 스킵 (|---|---|)
        if cells and all(re.match(r"^:?-+:?$", c) for c in cells if c.strip()):
            continue
        if cells:
            rows.append(cells)
    return rows


def _split_content_tables(content: str) -> list[tuple[str, bool]]:
    """
    섹션 내용을 테이블 블록과 일반 텍스트 블록으로 분리.
    반환: [(텍스트, is_table), ...]
    """
    segments: list[tuple[str, bool]] = []
    current: list[str] = []
    in_table = False

    for line in content.split("\n"):
        stripped = line.strip()
        is_table_line = (
            stripped.startswith("|") and stripped.endswith("|") and len(stripped) > 2
        )

        if is_table_line and not in_table:
            if current:
                segments.append(("\n".join(current), False))
                current = []
            in_table = True
            current = [line]
        elif is_table_line and in_table:
            current.append(line)
        elif not is_table_line and in_table:
            segments.append(("\n".join(current), True))
            current = [line]
            in_table = False
        else:
            current.append(line)

    if current:
        segments.append(("\n".join(current), in_table))

    return segments


# 불릿 접두사 패턴: - • ▸ * ① ② ③ ... ⑩  또는  1. 2. 3.  또는  1) 2) 3)
_BULLET_PAT = re.compile(
    r"^(?:"
    r"[-•·▪▸*]"                         # 일반 불릿 기호
    r"|[①②③④⑤⑥⑦⑧⑨⑩]"              # 원문자 ①~⑩
    r"|\d{1,2}[.\)]\s"                   # 1. 2. 3. / 1) 2) 3)
    r")\s*"
)


def _parse_bullets(content: str, keep_links: bool = False) -> list:
    """
    섹션 내용에서 불릿 항목 추출.

    인식하는 불릿 접두사:
      - / • / · / ▪ / ▸ / *   (일반 기호)
      ① ② ③ ... ⑩            (원문자, LLM 핵심요약에 자주 사용)
      1. 2. 3. / 1) 2)         (숫자 + 마침표/괄호)

    keep_links=True: URL을 [Link] 하이퍼링크로 변환 (핵심 요약용)
    반환: list[str] 또는 keep_links=True 시 list[list[dict]] (Notion rich_text)
    """
    result = []
    for raw in content.split("\n"):
        line = raw.strip()
        if not line:
            continue
        m = _BULLET_PAT.match(line)
        if m:
            cleaned = line[m.end():].strip()
            cleaned = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", cleaned)
            if not cleaned:
                continue
            if keep_links:
                result.append(_rich_text_with_links(cleaned))
            else:
                cleaned = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", cleaned)
                result.append(cleaned[:1900])
    return result


def _notion_needs_title(title: str, url: str) -> bool:
    """
    Notion 저장 시 제목 스크래핑이 필요한지 판단.
    - 제목이 없거나 빈 문자열
    - URL 자체가 제목으로 들어온 경우
    - 공백 없이 점이 있는 도메인형 문자열 (news.google.com, reuters.com 등)
    """
    if not title or not title.strip():
        return True
    t = title.strip()
    if t.startswith("http"):
        return True
    if " " not in t and "." in t and len(t) < 60:
        return True
    return False


def _fetch_notion_title(url: str) -> str:
    """
    BeautifulSoup으로 URL의 <title> 태그를 파싱해 기사 제목 반환.
    실패 시 도메인 이름 반환 (예: reuters.com).

    collector.fetch_page_title()을 재사용.
    """
    try:
        from .collector import fetch_page_title
        fetched = fetch_page_title(url, timeout=4)
        if fetched:
            return fetched[:120]
    except Exception:
        pass
    # fallback: 도메인 이름
    try:
        from urllib.parse import urlparse
        return urlparse(url).netloc.replace("www.", "") or url[:60]
    except Exception:
        return url[:60]


def _source_item_bullet(title: str, url: str) -> dict:
    """
    참조 URL 항목 하나를 Notion bulleted_list_item 블록으로 변환.
    형식: ● [기사 제목]  [Link](URL)
    """
    title_clean = title.strip()[:150] or url[:60]
    rich_text = [
        {"type": "text",
         "text": {"content": f"● {title_clean}  "}},
        {"type": "text",
         "text": {"content": "[Link]", "link": {"url": url}},
         "annotations": {"color": "blue", "underline": True, "bold": False}},
    ]
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": rich_text},
    }


def _get_title_prop_name(client: Client, db_id: str) -> str:
    """DB의 타이틀 속성 이름을 동적으로 감지 (한국어 UI: '이름', 영어 UI: 'Name')."""
    # 1차: DB retrieve로 속성 스키마 조회
    try:
        db = client.databases.retrieve(database_id=db_id)
        for pname, pinfo in db.get("properties", {}).items():
            if pinfo.get("type") == "title":
                return pname
    except Exception:
        pass
    # 2차: 최근 페이지 1개로 추론
    try:
        pages = _notion_query(db_id, page_size=1)
        if pages:
            for pname, pinfo in pages[0].get("properties", {}).items():
                if pinfo.get("type") == "title":
                    return pname
    except Exception:
        pass
    return "이름"   # 한국어 Notion 기본값


def _build_properties(title_prop: str, title: str, analysis: dict,
                      date_str: str, report_type: str,
                      all_props: set) -> dict:
    """DB에 존재하는 속성만 포함해 properties dict 생성."""
    props: dict = {
        title_prop: {"title": _rich_text(title)},
    }
    # ── 날짜 (Date 또는 날짜 속성) ──────────────────────────────
    for date_key in ("Date", "날짜", "date"):
        if date_key in all_props:
            props[date_key] = {"date": {"start": date_str}}
            break
    # ── 리포트 타입 ──────────────────────────────────────────────
    if "Type" in all_props:
        props["Type"] = {"select": {"name": report_type}}
    # ── 키워드 ───────────────────────────────────────────────────
    if "Keywords" in all_props:
        props["Keywords"] = {"multi_select": _safe_kw_list(
            analysis.get("keywords_found", []))}
    # ── 기사 수 ──────────────────────────────────────────────────
    if "Articles" in all_props:
        props["Articles"] = {"number": analysis.get("article_count", 0)}
    # ── 요약 (사용자가 Notion DB에 추가한 경우) ──────────────────
    for summary_key in ("요약", "Summary", "summary"):
        if summary_key in all_props:
            summary = _extract_summary_text(analysis)
            if summary:
                props[summary_key] = {"rich_text": _rich_text(summary[:2000])}
            break
    return props


def _get_db_prop_names(client: Client, db_id: str) -> set:
    """DB에 실제로 존재하는 속성 이름 집합 반환."""
    # DB retrieve로 스키마에서 직접 가져오기 (query 불필요)
    try:
        db = client.databases.retrieve(database_id=db_id)
        return set(db.get("properties", {}).keys())
    except Exception:
        pass
    # 폴백: 최근 페이지 1개에서 추론
    try:
        pages = _notion_query(db_id, page_size=1)
        if pages:
            return set(pages[0].get("properties", {}).keys())
    except Exception:
        pass
    return set()


def _send_blocks(client: Client, page_id: str, blocks: list[dict]) -> None:
    """블록을 100개 단위로 나눠 Notion에 전송."""
    for i in range(0, len(blocks), 100):
        batch = blocks[i: i + 100]
        try:
            client.blocks.children.append(block_id=page_id, children=batch)
            logger.debug("블록 전송 %d~%d 완료", i, i + len(batch))
        except APIResponseError as e:
            logger.error("블록 전송 실패 (%d~%d): %s", i, i + len(batch), e)
            raise


def _create_page_safe(client: Client, db_id: str, title: str,
                      analysis: dict, date_str: str,
                      report_type: str, blocks: list[dict]) -> dict:
    """
    페이지 생성 — 속성 오류 시 자동 축소 재시도.
    1차: 풀 속성 / 2차: 타이틀만 / 3차: 빈 properties
    """
    title_prop  = _get_title_prop_name(client, db_id)
    all_props   = _get_db_prop_names(client, db_id)
    logger.info("타이틀 속성: '%s', 존재 속성: %s", title_prop, all_props)

    # 1차 시도: 풀 속성
    try:
        props = _build_properties(title_prop, title, analysis,
                                  date_str, report_type, all_props)
        return client.pages.create(
            parent={"database_id": db_id},
            properties=props,
            children=blocks[:100],
        )
    except APIResponseError as e:
        logger.warning("1차 시도 실패: %s", e)

    # 2차 시도: 타이틀만
    try:
        return client.pages.create(
            parent={"database_id": db_id},
            properties={title_prop: {"title": _rich_text(title)}},
            children=blocks[:100],
        )
    except APIResponseError as e:
        logger.warning("2차 시도 실패: %s", e)

    # 3차 시도: 빈 properties (내용은 블록으로만)
    return client.pages.create(
        parent={"database_id": db_id},
        properties={},
        children=blocks[:100],
    )


# ══════════════════════════════════════════════════════════════════════════════
# Public: Daily 저장
# ══════════════════════════════════════════════════════════════════════════════

def save_daily_to_notion(analysis: dict) -> str:
    """
    Daily 분석 결과를 Notion DB에 새 페이지로 저장.
    반환: 생성된 페이지 URL (실패 시 빈 문자열)
    """
    db_id = os.environ.get("NOTION_DAILY_DB_ID", "").strip()
    if not db_id:
        raise ValueError("NOTION_DAILY_DB_ID 환경변수가 없습니다.")

    client   = _get_client()
    date_str = datetime.now(KST).strftime("%Y-%m-%d")   # KST 기준 날짜
    if analysis.get("date"):
        date_str = analysis["date"]
    title    = f"[Daily] {date_str} AI/Semiconductor News"   # 짧은 타이틀
    blocks   = _build_blocks(analysis)

    # ── '날짜' Date 속성이 없으면 자동으로 추가 (최초 1회) ──────────────────
    ensure_date_property(db_id)

    logger.info("Notion 페이지 생성 중 (블록 %d개)...", len(blocks))

    page     = _create_page_safe(client, db_id, title, analysis,
                                 date_str, "Daily", blocks)
    page_id  = page["id"]
    page_url = page.get("url", "")
    logger.info("페이지 생성 완료: %s", page_url)

    # ── 나머지 블록 추가 전송 ─────────────────────────────────
    if len(blocks) > 100:
        logger.info("추가 블록 전송 중 (%d개)...", len(blocks) - 100)
        _send_blocks(client, page_id, blocks[100:])

    logger.info("Notion Daily 저장 완료 (%d개 블록)", len(blocks))
    return page_url


# ══════════════════════════════════════════════════════════════════════════════
# Public: Weekly 저장
# ══════════════════════════════════════════════════════════════════════════════

def save_weekly_to_notion(analysis: dict, week_label: str) -> str:
    """Weekly 보고서를 Notion DB에 저장."""
    db_id = os.environ.get("NOTION_WEEKLY_DB_ID", "").strip()
    if not db_id:
        raise ValueError("NOTION_WEEKLY_DB_ID 환경변수가 없습니다.")

    client   = _get_client()
    today    = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    title    = f"[Weekly] {week_label} AI/Semiconductor Intelligence Report"
    blocks   = _build_blocks(analysis)

    page     = _create_page_safe(client, db_id, title, analysis,
                                 today, "Weekly", blocks)
    page_id  = page["id"]
    page_url = page.get("url", "")

    if len(blocks) > 100:
        _send_blocks(client, page_id, blocks[100:])

    logger.info("Notion Weekly 저장 완료: %s", page_url)
    return page_url


# ══════════════════════════════════════════════════════════════════════════════
# Public: Weekly용 Daily 데이터 조회
# ══════════════════════════════════════════════════════════════════════════════

def fetch_weekly_analyses(days: int = 7) -> list[dict]:
    """Daily DB에서 최근 N일 분석 조회."""
    from datetime import timedelta

    db_id   = os.environ.get("NOTION_DAILY_DB_ID", "").strip()
    client  = _get_client()
    cutoff  = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")

    results = []
    try:
        results = _notion_query(
            db_id,
            sorts=[{"timestamp": "created_time", "direction": "ascending"}],
            page_size=50,
        )
    except Exception as e:
        logger.warning("DB 쿼리 실패: %s", e)

    logger.info("Notion Daily 조회: %d개", len(results))

    analyses = []
    for page in results:
        # 날짜: Date 속성 또는 created_time 사용
        date_prop = page["properties"].get("Date", {}).get("date") or {}
        date_str  = date_prop.get("start", "")
        if not date_str:
            date_str = page.get("created_time", "")[:10]
        raw_text  = _extract_page_text(client, page["id"])
        analyses.append({"date": date_str, "raw": raw_text, "article_count": 0})

    return analyses


def _extract_page_text(client: Client, page_id: str) -> str:
    """
    페이지 블록 전체 텍스트 추출.
    _rich_text_with_links()가 URL을 'plain_text="클릭"' + link 어노테이션으로 저장하므로,
    plain_text가 "클릭" 등인 경우 실제 URL을 복원해 반환한다.
    """
    _LINK_PLACEHOLDERS = {"클릭", "링크", "Link", "[Link]", "link", "source"}

    lines, cursor = [], None
    while True:
        kwargs: dict = {"block_id": page_id}
        if cursor:
            kwargs["start_cursor"] = cursor
        resp = client.blocks.children.list(**kwargs)
        for block in resp.get("results", []):
            btype = block.get("type", "")
            rich  = block.get(btype, {}).get("rich_text", [])
            parts: list[str] = []
            for r in rich:
                plain    = r.get("plain_text", "")
                link_obj = (r.get("text") or {}).get("link") or {}
                url_val  = link_obj.get("url", "") if isinstance(link_obj, dict) else ""
                # "클릭" 같은 플레이스홀더는 실제 URL로 교체
                if url_val and plain in _LINK_PLACEHOLDERS:
                    parts.append(url_val)
                else:
                    parts.append(plain)
            text = "".join(parts)
            if text:
                lines.append(text)
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# Public: Notion DB 날짜 속성 추가
# ══════════════════════════════════════════════════════════════════════════════

def diagnose_notion_db(db_id: str | None = None) -> dict:
    """
    Notion Daily DB 연결 상태 진단.
    반환: {token_ok, db_id_hint, error, props, recent_pages}
    """
    if not db_id:
        db_id = os.environ.get("NOTION_DAILY_DB_ID", "").strip()
    token = os.environ.get("NOTION_TOKEN", "")
    result: dict = {
        "token_ok":     bool(token),
        "db_id_hint":   (db_id[:8] + "...") if db_id else "미설정",
        "db_id_full":   db_id,
        "error":        None,
        "props":        [],
        "recent_pages": [],   # [{title, created_utc, created_kst}]
        "title_prop":   "?",
    }
    if not token:
        result["error"] = "NOTION_TOKEN 미설정"
        return result
    if not db_id:
        result["error"] = "NOTION_DAILY_DB_ID 미설정"
        return result

    try:
        client = _get_client()

        # DB 속성 목록
        db = client.databases.retrieve(database_id=db_id)
        result["props"] = list(db.get("properties", {}).keys())

        # 타이틀 속성명
        title_prop = _get_title_prop_name(client, db_id)
        result["title_prop"] = title_prop

        # 최근 5개 페이지
        recent = _notion_query(
            db_id,
            sorts=[{"timestamp": "created_time", "direction": "descending"}],
            page_size=5,
        )
        for page in recent:
            props      = page.get("properties", {})
            title_rich = props.get(title_prop, {}).get("title", [])
            title_text = "".join(r.get("plain_text", "") for r in title_rich)
            created    = page.get("created_time", "")[:16]
            # KST 변환
            kst_date = ""
            try:
                from datetime import datetime, timezone as _tz, timedelta as _td
                dt       = datetime.fromisoformat(created + ":00+00:00")
                kst_date = dt.astimezone(_tz(_td(hours=9))).strftime("%Y-%m-%d %H:%M")
            except Exception:
                kst_date = created
            result["recent_pages"].append({
                "title":       title_text[:80] or "(제목 없음)",
                "created_utc": created,
                "created_kst": kst_date,
            })
    except Exception as e:
        result["error"] = str(e)

    return result


def ensure_date_property(db_id: str | None = None) -> bool:
    """
    Daily DB에 '날짜' Date 속성이 없으면 자동으로 추가.
    이미 있으면 스킵. 반환값: 성공 여부.
    """
    if not db_id:
        db_id = os.environ.get("NOTION_DAILY_DB_ID", "").strip()
    if not db_id:
        return False
    try:
        client = _get_client()
        db = client.databases.retrieve(database_id=db_id)
        existing = set(db.get("properties", {}).keys())
        if any(p in existing for p in ("날짜", "Date", "date")):
            logger.debug("날짜 속성이 이미 존재합니다: %s", existing & {"날짜", "Date", "date"})
            return True
        # 없으면 추가
        client.databases.update(
            database_id=db_id,
            properties={"날짜": {"date": {}}},
        )
        logger.info("'날짜' Date 속성을 DB에 추가했습니다.")
        return True
    except Exception as e:
        logger.warning("날짜 속성 추가 실패: %s", e)
        return False


# ══════════════════════════════════════════════════════════════════════════════
# Public: Daily 데이터 날짜별 조회
# ══════════════════════════════════════════════════════════════════════════════

# ── 섹션 헤딩 변형 사전 ──────────────────────────────────────────────────────
# LLM 템플릿: "## 1. 핵심 요약" → _parse_sections() 키: "1. 핵심 요약"
# Notion 블록으로 저장 후 읽으면: "1. 핵심 요약" (## 없음)
# 아래 dict: canonical 제목 → 실제로 나타날 수 있는 모든 변형 목록
_SECTION_HEADING_VARIANTS: dict[str, list[str]] = {
    "핵심 요약":        ["핵심 요약",        "1. 핵심 요약"],
    "기술적 의미":      ["기술적 의미",      "기술적 의미 분석",
                         "2. 기술적 의미 분석", "2. 기술적 의미"],
    "AI Agent":         ["AI Agent",         "AI Agent 아키텍처 영향",
                         "3. AI Agent 아키텍처 영향", "3. AI Agent"],
    "비즈니스 영향":    ["비즈니스 영향",    "4. 비즈니스 영향"],
    "Ecosystem":        ["Ecosystem",        "Ecosystem 영향",
                         "5. Ecosystem 영향", "5. Ecosystem"],
    "향후 전망":        ["향후 전망",        "6. 향후 전망"],
    "메모리":           ["메모리",           "메모리·스토리지 시장 영향",
                         "7. 메모리·스토리지 시장 영향", "7. 메모리"],
    "스토리지 Workload": ["스토리지 Workload", "스토리지 Workload 심층 분석",
                          "8. 스토리지 Workload 심층 분석", "8. 스토리지 Workload"],
    "지역별":           ["지역별",           "지역별 동향 분석",
                         "9. 지역별 동향 분석", "9. 지역별"],
    "Why Now":          ["Why Now",          "Why Now?",
                         "Why Now? — 전략적 시급성",
                         "10. Why Now? — 전략적 시급성", "10. Why Now"],
}

# 변형 → canonical 역매핑 (빠른 조회용)
_VARIANT_TO_CANONICAL: dict[str, str] = {
    v: canon
    for canon, variants in _SECTION_HEADING_VARIANTS.items()
    for v in variants
}


def _match_heading(stripped: str) -> str | None:
    """
    한 줄 텍스트가 섹션 헤딩인지 판단하고 canonical 제목 반환.
    None 이면 헤딩 아님.

    3단계 탐지:
    1) 정확 일치       : "1. 핵심 요약"  / "핵심 요약"
    2) 번호 접두어     : "10. Why Now? — 전략적 시급성"  →  body 부분으로 재시도
    3) ## 접두어       : "## 1. 핵심 요약"  (sections 파싱 실패로 raw가 paragraph에 저장된 경우)
                         → ## 제거 후 1~2 단계 재귀 적용
    """
    # 1단계: 정확 일치
    c = _VARIANT_TO_CANONICAL.get(stripped)
    if c:
        return c

    # 2단계: "N. body" 형식
    m = re.match(r"^\d{1,2}[\.\)]\s+(.+)$", stripped)
    if m:
        body = m.group(1).strip()
        c = _VARIANT_TO_CANONICAL.get(body)
        if c:
            return c
        # body가 variants 중 하나로 시작하는지 확인 (부분 일치 fallback)
        for canon, variants in _SECTION_HEADING_VARIANTS.items():
            if any(body.startswith(v) for v in variants):
                return canon

    # 3단계: "## heading" 또는 "## N. heading" 형식
    #   → sections 파싱 실패로 LLM raw 출력이 paragraph 블록으로 저장됐을 때
    m2 = re.match(r"^#{1,3}\s+(.+)$", stripped)
    if m2:
        inner = m2.group(1).strip()
        return _match_heading(inner)   # 재귀: ## 제거 후 1~2단계 재시도

    return None


def _parse_raw_to_sections(raw_text: str) -> dict:
    """
    Notion 페이지 블록에서 추출한 raw 텍스트 → 섹션 제목 : 내용 dict 파싱.

    지원 형식:
    - "1. 핵심 요약"              (heading_2 블록, 정상 저장된 경우)
    - "핵심 요약"                 (heading_2 블록, 번호 없는 경우)
    - "## 1. 핵심 요약"           (paragraph 블록, sections 비어있어 raw가 저장된 경우)
    - "## 핵심 요약"              (위와 동일)
    """
    sections: dict = {}
    current_title: str | None = None
    current_lines: list[str] = []

    for line in raw_text.split("\n"):
        stripped = line.strip()
        canonical = _match_heading(stripped)

        if canonical:
            if current_title and current_lines:
                sections[current_title] = "\n".join(current_lines).strip()
            current_title = canonical
            current_lines = []
        elif current_title:
            # "##" 로 시작하는 비-헤딩 줄(소제목 등)은 ### 이하이면 유지
            current_lines.append(line)

    if current_title and current_lines:
        sections[current_title] = "\n".join(current_lines).strip()

    return sections


def _parse_source_items_from_raw(raw_text: str) -> list[dict]:
    """
    raw_text에서 "📚 참조 URL" 섹션을 찾아 source_items 리스트 복원.

    저장 형식 (Fix B 이후):
        기사 제목  https://example.com/article
    구분자: URL 앞에 두 칸 이상 공백 또는 탭

    구형 형식 (URL만 저장):
        https://example.com/article
    """
    URL_RE    = re.compile(r'(https?://\S+)')
    SPLIT_RE  = re.compile(r'\s{2,}|\t')   # 두 칸 이상 공백 또는 탭
    items: list[dict] = []
    in_section = False

    for line in raw_text.split("\n"):
        stripped = line.strip()

        # 섹션 시작 감지
        if "참조 URL" in stripped or "📚" in stripped:
            in_section = True
            continue

        # 다른 헤딩이 나오면 섹션 종료
        if in_section and stripped and not stripped.startswith("-") and not stripped.startswith("•"):
            # heading_2 또는 callout 형태의 줄이면 종료
            if _match_heading(stripped) or len(stripped) < 5:
                if not URL_RE.search(stripped):
                    in_section = False
                    continue

        if not in_section:
            continue

        url_m = URL_RE.search(stripped)
        if not url_m:
            continue

        url   = url_m.group(1).rstrip(".,;)")
        # 제목: URL 앞 부분 추출 (두 칸+ 공백 또는 URL 직전까지)
        before_url = stripped[:url_m.start()].strip()
        # "- " 등 불릿 마커 제거
        before_url = re.sub(r"^[-•·▪▸*]\s*", "", before_url).strip()
        # SPLIT_RE 기준으로 마지막 토큰이 URL일 경우 앞부분이 제목
        parts = SPLIT_RE.split(before_url)
        title = parts[0].strip() if parts else ""

        if url:
            items.append({"title": title, "url": url, "source": "", "summary": ""})

    return items[:20]


def fetch_daily_from_notion(date_str: str) -> dict | None:
    """
    Notion Daily DB에서 특정 날짜의 분석 페이지를 불러와 analysis dict 반환.

    3단계 조회 전략:
    1차: '날짜' Date 속성 = date_str 필터
    2차: 제목 contains date_str 필터 (API 필터)
    3차: 최근 30개 페이지 직접 스캔 (제목 plain_text 검사 + KST created_time 대조)
         → API 필터가 예상대로 동작하지 않을 때 안전망
    """
    db_id = os.environ.get("NOTION_DAILY_DB_ID", "").strip()
    if not db_id:
        raise ValueError("NOTION_DAILY_DB_ID 환경변수가 없습니다.")

    client = _get_client()

    # ── DB 속성 목록 + 타이틀 속성명 확인 ────────────────────────────────────
    try:
        db        = client.databases.retrieve(database_id=db_id)
        all_props = set(db.get("properties", {}).keys())
    except Exception as e:
        logger.warning("DB 속성 조회 실패: %s", e)
        all_props = set()

    date_prop_name = next(
        (p for p in ("날짜", "Date", "date") if p in all_props), None
    )
    title_prop = _get_title_prop_name(client, db_id)
    logger.info("DB 속성: %s | 타이틀 속성: %s | 날짜 속성: %s",
                all_props, title_prop, date_prop_name)

    pages: list = []

    # ── 1차: Date 속성 필터 ───────────────────────────────────────────────────
    if date_prop_name:
        try:
            pages = _notion_query(
                db_id,
                filter_body={"property": date_prop_name, "date": {"equals": date_str}},
                sorts=[{"timestamp": "created_time", "direction": "descending"}],
                page_size=5,
            )
            logger.info("1차(Date 필터 %s=%s): %d건", date_prop_name, date_str, len(pages))
        except Exception as e:
            logger.warning("1차 Date 필터 실패: %s", e)

    # ── 2차: 제목 contains 필터 ──────────────────────────────────────────────
    if not pages:
        try:
            pages = _notion_query(
                db_id,
                filter_body={"property": title_prop, "title": {"contains": date_str}},
                sorts=[{"timestamp": "created_time", "direction": "descending"}],
                page_size=5,
            )
            logger.info("2차(제목 contains '%s'): %d건", date_str, len(pages))
        except Exception as e:
            logger.warning("2차 제목 필터 실패: %s", e)

    # ── 3차: 최근 30개 페이지 직접 스캔 (안전망) ─────────────────────────────
    if not pages:
        try:
            all_recent = _notion_query(
                db_id,
                sorts=[{"timestamp": "created_time", "direction": "descending"}],
                page_size=30,
            )
            logger.info("3차 스캔: DB 최근 %d개 페이지 검사 중", len(all_recent))

            # date_str 변형 목록: "2026-05-10" → "26-05-10" / "20260510" 등 허용
            date_variants = {
                date_str,                          # "2026-05-10"
                date_str.replace("-", ""),         # "20260510"
                date_str[2:],                      # "26-05-10"
            }

            for page in all_recent:
                props = page.get("properties", {})

                # 타이틀 plain_text 추출
                title_rich = props.get(title_prop, {}).get("title", [])
                title_text = "".join(r.get("plain_text", "") for r in title_rich)

                # created_time → KST 변환 후 날짜 비교
                created_utc = page.get("created_time", "")[:16]  # "2026-05-09T23:00"
                created_kst = ""
                try:
                    from datetime import datetime, timezone, timedelta
                    _KST = timezone(timedelta(hours=9))
                    dt   = datetime.fromisoformat(created_utc + ":00+00:00")
                    created_kst = dt.astimezone(_KST).strftime("%Y-%m-%d")
                except Exception:
                    pass

                matched = (
                    any(v in title_text for v in date_variants)
                    or created_kst == date_str
                )
                logger.info("  페이지: '%s' | created_kst=%s | 매칭=%s",
                            title_text[:60], created_kst, matched)

                if matched:
                    pages = [page]
                    logger.info("3차 스캔으로 페이지 발견: %s", title_text[:60])
                    break
        except Exception as e:
            logger.warning("3차 스캔 실패: %s", e)

    if not pages:
        logger.info("Notion: %s 날짜 분석 없음 (3단계 모두 실패)", date_str)
        return None

    # ── 첫 번째 페이지 파싱 ───────────────────────────────────────────────────
    page     = pages[0]
    page_id  = page["id"]
    page_url = page.get("url", "")
    props    = page.get("properties", {})

    # ── Notion DB 컬럼에서 키워드·기사 수 읽기 ──────────────────────────────
    keywords: list[str] = []
    kw_prop = props.get("Keywords", {})
    if kw_prop.get("type") == "multi_select":
        keywords = [opt["name"] for opt in kw_prop.get("multi_select", [])]

    article_count = 0
    art_prop = props.get("Articles", {})
    if art_prop.get("type") == "number" and art_prop.get("number") is not None:
        article_count = int(art_prop["number"])

    # ── 페이지 본문 → 섹션 파싱 ──────────────────────────────────────────────
    logger.info("Notion 페이지 블록 추출 중: %s", page_id)
    raw_text = _extract_page_text(client, page_id)
    sections = _parse_raw_to_sections(raw_text)

    # ── raw 텍스트에서 메타 정보 보완 (DB 컬럼 없을 때 폴백) ─────────────────
    if article_count == 0:
        m = re.search(r'수집 기사[:\s]*(\d+)건', raw_text)
        if m:
            article_count = int(m.group(1))

    if not keywords:
        m = re.search(r'키워드[:\s]*([^\n]{3,200})', raw_text)
        if m:
            keywords = [k.strip() for k in m.group(1).split(',') if k.strip()][:12]

    # ── raw 텍스트에서 AI 기여 모델 복원 ────────────────────────────────────
    attribution = f"Notion 캐시 ({date_str})"
    m = re.search(r'AI[:\s]+([^\n|]{5,80})', raw_text)
    if m:
        attribution = m.group(1).strip().rstrip('|').strip()

    # ── 참조 URL 섹션에서 source_items 복원 ─────────────────────────────────
    # Fix B 이후 저장 형식: "기사 제목  https://..." (두 칸 이상 공백으로 title/url 구분)
    source_items = _parse_source_items_from_raw(raw_text)

    return {
        "date":              date_str,
        "article_count":     article_count,
        "keywords_found":    keywords,
        "sections":          sections,
        "raw":               raw_text,
        "notion_url":        page_url,
        "provider":          "Notion",
        "model_attribution": attribution,
        "source_items":      source_items,
        "source_urls":       [item["url"] for item in source_items],
        "filter_meta":       {"used_groq": False},
        "research_meta":     {"used_gemini": False},
        "from_notion_cache": True,   # 대시보드에서 캐시 여부 구분용
    }
