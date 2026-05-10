"""Notion API를 통해 분석 결과를 DB 페이지로 저장합니다."""
import logging
import os
import re
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))

from notion_client import Client
from notion_client.errors import APIResponseError

logger = logging.getLogger(__name__)

_MAX_BLOCK_TEXT = 1900   # Notion 블록 하나당 최대 글자 수 (한도 2000)


# ══════════════════════════════════════════════════════════════════════════════
# 내부 유틸
# ══════════════════════════════════════════════════════════════════════════════

def _get_client() -> Client:
    token = os.environ.get("NOTION_TOKEN", "")
    if not token:
        raise ValueError("NOTION_TOKEN 환경변수가 없습니다.")
    return Client(auth=token)


def _rich_text(content: str) -> list[dict]:
    """Notion rich_text 포맷. 2000자 초과 시 자름."""
    return [{"type": "text", "text": {"content": content[:2000]}}]


def _rich_text_with_links(text: str) -> list[dict]:
    """URL 패턴을 '클릭' 하이퍼링크로 변환한 Notion rich_text."""
    URL_PAT = re.compile(
        r'\[(?:출처|링크|Source|참조)[:\s]*(https?://[^\]]+)\]'
        r'|(https?://\S{15,})'
    )
    result: list[dict] = []
    last = 0
    for m in URL_PAT.finditer(text):
        url = (m.group(1) or m.group(2) or "").strip()
        before = text[last:m.start()].strip()
        if before:
            result.append({"type": "text", "text": {"content": before + " "}})
        if url:
            result.append({"type": "text",
                           "text": {"content": "클릭", "link": {"url": url}},
                           "annotations": {"color": "blue", "underline": True}})
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
    """긴 텍스트를 여러 paragraph 블록으로 분할."""
    if not text or not text.strip():
        return []
    chunks = [text[i: i + _MAX_BLOCK_TEXT]
              for i in range(0, len(text), _MAX_BLOCK_TEXT)]
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

    # ── 출처 URL 목록 ─────────────────────────────────────────
    source_urls = analysis.get("source_urls", [])
    if source_urls:
        blocks.append(_heading_block("📚 참조 URL"))
        for url in source_urls[:20]:
            blocks.append(_bullet_block(url))

    return blocks


def _parse_bullets(content: str, keep_links: bool = False) -> list:
    """
    섹션 내용에서 불릿 항목 추출.
    keep_links=True: URL을 유지 (핵심 요약용 rich_text 변환 대상)
    반환: list[str] 또는 keep_links=True 시 list[list[dict]] (rich_text 포맷)
    """
    result = []
    for raw in content.split("\n"):
        line = raw.strip()
        if line.startswith(("-", "•", "·", "▪", "▸", "*")):
            cleaned = line.lstrip("-•·▪▸*").strip()
            cleaned = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", cleaned)
            if not cleaned:
                continue
            if keep_links:
                result.append(_rich_text_with_links(cleaned))
            else:
                cleaned = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", cleaned)
                result.append(cleaned[:1900])
    return result


def _get_title_prop_name(client: Client, db_id: str) -> str:
    """DB의 타이틀 속성 이름을 동적으로 감지 (한국어 UI: '이름', 영어 UI: 'Name')."""
    try:
        result = client.databases.query(**{"database_id": db_id, "page_size": 1})
        pages = result.get("results", [])
        if pages:
            for pname, pinfo in pages[0].get("properties", {}).items():
                if pinfo.get("type") == "title":
                    return pname
    except Exception:
        pass
    # 페이지 없으면 직접 retrieve 시도 (구버전 Notion)
    try:
        db = client.databases.retrieve(database_id=db_id)
        for pname, pinfo in db.get("properties", {}).items():
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
    try:
        result = client.databases.query(**{"database_id": db_id, "page_size": 1})
        pages = result.get("results", [])
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

    results, cursor = [], None
    while True:
        kwargs: dict = {
            "database_id": db_id,
            "sorts": [{"timestamp": "created_time", "direction": "ascending"}],
        }
        if cursor:
            kwargs["start_cursor"] = cursor
        try:
            resp = client.databases.query(**kwargs)
        except Exception as e:
            logger.warning("DB 쿼리 실패: %s", e)
            break
        results.extend(resp.get("results", []))
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")

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
    """페이지 블록 전체 텍스트 추출."""
    lines, cursor = [], None
    while True:
        kwargs: dict = {"block_id": page_id}
        if cursor:
            kwargs["start_cursor"] = cursor
        resp = client.blocks.children.list(**kwargs)
        for block in resp.get("results", []):
            btype = block.get("type", "")
            rich  = block.get(btype, {}).get("rich_text", [])
            text  = "".join(r.get("plain_text", "") for r in rich)
            if text:
                lines.append(text)
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# Public: Notion DB 날짜 속성 추가
# ══════════════════════════════════════════════════════════════════════════════

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

_SECTION_HEADINGS = [
    "핵심 요약", "기술적 의미", "AI Agent", "비즈니스 영향",
    "Ecosystem", "향후 전망", "메모리", "스토리지 Workload",
    "지역별", "Why Now",
]


def _parse_raw_to_sections(raw_text: str) -> dict:
    """
    페이지 블록에서 추출한 raw 텍스트를 섹션 제목 → 내용 dict 로 파싱.
    Notion heading_2 블록 → 섹션 구분자로 사용.
    """
    sections: dict = {}
    current_title: str | None = None
    current_lines: list[str] = []

    for line in raw_text.split("\n"):
        stripped = line.strip()
        matched = next(
            (h for h in _SECTION_HEADINGS
             if h in stripped and len(stripped) < 80),
            None,
        )
        if matched:
            if current_title and current_lines:
                sections[current_title] = "\n".join(current_lines).strip()
            current_title = matched
            current_lines = []
        elif current_title:
            current_lines.append(line)

    if current_title and current_lines:
        sections[current_title] = "\n".join(current_lines).strip()

    return sections


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
            resp  = client.databases.query(
                database_id=db_id,
                filter={"property": date_prop_name, "date": {"equals": date_str}},
                sorts=[{"timestamp": "created_time", "direction": "descending"}],
                page_size=5,
            )
            pages = resp.get("results", [])
            logger.info("1차(Date 필터 %s=%s): %d건", date_prop_name, date_str, len(pages))
        except Exception as e:
            logger.warning("1차 Date 필터 실패: %s", e)

    # ── 2차: 제목 contains 필터 (API) ────────────────────────────────────────
    if not pages:
        try:
            resp  = client.databases.query(
                database_id=db_id,
                filter={"property": title_prop, "title": {"contains": date_str}},
                sorts=[{"timestamp": "created_time", "direction": "descending"}],
                page_size=5,
            )
            pages = resp.get("results", [])
            logger.info("2차(제목 contains '%s'): %d건", date_str, len(pages))
        except Exception as e:
            logger.warning("2차 제목 필터 실패: %s", e)

    # ── 3차: 최근 30개 페이지 직접 스캔 (안전망) ─────────────────────────────
    if not pages:
        try:
            resp       = client.databases.query(
                database_id=db_id,
                sorts=[{"timestamp": "created_time", "direction": "descending"}],
                page_size=30,
            )
            all_recent = resp.get("results", [])
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

    # 키워드
    keywords: list[str] = []
    kw_prop = props.get("Keywords", {})
    if kw_prop.get("type") == "multi_select":
        keywords = [opt["name"] for opt in kw_prop.get("multi_select", [])]

    # 기사 수
    article_count = 0
    art_prop = props.get("Articles", {})
    if art_prop.get("type") == "number" and art_prop.get("number") is not None:
        article_count = int(art_prop["number"])

    # 페이지 본문 → 섹션 파싱
    logger.info("Notion 페이지 블록 추출 중: %s", page_id)
    raw_text = _extract_page_text(client, page_id)
    sections = _parse_raw_to_sections(raw_text)

    return {
        "date":              date_str,
        "article_count":     article_count,
        "keywords_found":    keywords,
        "sections":          sections,
        "raw":               raw_text,
        "notion_url":        page_url,
        "provider":          "Notion",
        "model_attribution": f"Notion 캐시 ({date_str})",
        "source_urls":       [],
        "filter_meta":       {"used_groq": False},
        "research_meta":     {"used_gemini": False},
    }
