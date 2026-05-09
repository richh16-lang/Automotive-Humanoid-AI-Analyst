"""Notion API를 통해 분석 결과를 DB 페이지로 저장합니다."""
import logging
import os
from datetime import datetime, timezone

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


def _build_blocks(analysis: dict) -> list[dict]:
    """분석 결과 dict → Notion 블록 목록."""
    blocks: list[dict] = []

    # ── 메타 정보 callout ─────────────────────────────────────
    provider = analysis.get("provider") or analysis.get("model", "-")
    meta = (
        f"📅 날짜: {analysis.get('date', '-')}  |  "
        f"🤖 분석 엔진: {provider}  |  "
        f"📰 수집 기사: {analysis.get('article_count', 0)}건\n"
        f"🏷 키워드: {', '.join(analysis.get('keywords_found', []))}\n"
        f"📡 출처: {', '.join(analysis.get('sources', []))}"
    )
    blocks.append(_callout_block(meta, "📊"))
    blocks.append(_divider_block())

    # ── 10개 섹션 ─────────────────────────────────────────────
    sections: dict = analysis.get("sections", {})
    if sections:
        for title, content in sections.items():
            if title.strip():
                blocks.append(_heading_block(title))
            if content.strip():
                blocks.extend(_paragraph_blocks(content))
    else:
        # 섹션 파싱 실패 → raw 전체 삽입
        raw = analysis.get("raw", "")
        logger.warning("섹션 파싱 결과 없음, raw 텍스트 삽입 (%d자)", len(raw))
        blocks.extend(_paragraph_blocks(raw))

    return blocks


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
    if "Date" in all_props:
        props["Date"] = {"date": {"start": date_str}}
    if "Type" in all_props:
        props["Type"] = {"select": {"name": report_type}}
    if "Keywords" in all_props:
        props["Keywords"] = {"multi_select": _safe_kw_list(
            analysis.get("keywords_found", []))}
    if "Articles" in all_props:
        props["Articles"] = {"number": analysis.get("article_count", 0)}
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
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if analysis.get("date"):
        date_str = analysis["date"]
    title    = f"[Daily] {date_str} Automotive/AI Semiconductor 동향"
    blocks   = _build_blocks(analysis)

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
    title    = f"[Weekly] {week_label} Automotive/AI Semiconductor 주간 보고서"
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
