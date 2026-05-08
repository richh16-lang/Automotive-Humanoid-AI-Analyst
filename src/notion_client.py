"""Notion API를 통해 분석 결과를 DB 페이지로 저장합니다."""
import logging
import os
from datetime import datetime

from notion_client import Client

logger = logging.getLogger(__name__)

_MAX_TEXT_BLOCK = 1900  # Notion 단일 블록 최대 2000자


def _get_client() -> Client:
    return Client(auth=os.environ["NOTION_TOKEN"])


def _chunk_text(text: str, size: int = _MAX_TEXT_BLOCK) -> list[str]:
    """긴 텍스트를 Notion 블록 크기로 분할."""
    return [text[i : i + size] for i in range(0, len(text), size)] if text else [""]


def _rich_text(content: str) -> list[dict]:
    return [{"type": "text", "text": {"content": content[:2000]}}]


def _paragraph_blocks(text: str) -> list[dict]:
    """텍스트를 paragraph 블록 목록으로 변환."""
    blocks = []
    for chunk in _chunk_text(text):
        blocks.append(
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": _rich_text(chunk)},
            }
        )
    return blocks


def _heading2_block(text: str) -> dict:
    return {
        "object": "block",
        "type": "heading_2",
        "heading_2": {"rich_text": _rich_text(text[:100])},
    }


def _divider_block() -> dict:
    return {"object": "block", "type": "divider", "divider": {}}


def _build_daily_blocks(analysis: dict) -> list[dict]:
    """Daily 분석 결과를 Notion 블록 목록으로 변환."""
    blocks: list[dict] = []

    # 메타 정보
    meta = (
        f"수집 기사: {analysis.get('article_count', 0)}건  |  "
        f"모델: {analysis.get('model', '-')}  |  "
        f"키워드: {', '.join(analysis.get('keywords_found', []))}  |  "
        f"출처: {', '.join(analysis.get('sources', []))}"
    )
    blocks.extend(_paragraph_blocks(meta))
    blocks.append(_divider_block())

    sections: dict = analysis.get("sections", {})
    if sections:
        for title, content in sections.items():
            blocks.append(_heading2_block(title))
            blocks.extend(_paragraph_blocks(content))
    else:
        # 섹션 파싱 실패 시 raw 전체 삽입
        blocks.extend(_paragraph_blocks(analysis.get("raw", "")))

    return blocks


def save_daily_to_notion(analysis: dict) -> str:
    """
    Daily 분석 결과를 Notion DB에 새 페이지로 저장.
    반환값: 생성된 페이지 URL
    """
    client = _get_client()
    db_id = os.environ["NOTION_DAILY_DB_ID"]
    date_str = analysis.get("date", datetime.utcnow().strftime("%Y-%m-%d"))
    title = f"[Daily] {date_str} Automotive/AI Semiconductor 동향"

    blocks = _build_daily_blocks(analysis)
    # Notion API는 한 번에 최대 100개 블록만 허용
    first_batch = blocks[:100]

    page = client.pages.create(
        parent={"database_id": db_id},
        properties={
            "Name": {"title": _rich_text(title)},
            "Date": {"date": {"start": date_str}},
            "Type": {"select": {"name": "Daily"}},
            "Keywords": {
                "multi_select": [
                    {"name": kw}
                    for kw in analysis.get("keywords_found", [])[:5]
                ]
            },
            "Articles": {"number": analysis.get("article_count", 0)},
        },
        children=first_batch,
    )

    page_id = page["id"]
    page_url = page.get("url", "")

    # 100개 초과 블록 추가
    remaining = blocks[100:]
    for i in range(0, len(remaining), 100):
        client.blocks.children.append(
            block_id=page_id,
            children=remaining[i : i + 100],
        )

    logger.info("Notion Daily 페이지 생성 완료: %s", page_url)
    return page_url


def save_weekly_to_notion(analysis: dict, week_label: str) -> str:
    """Weekly 보고서를 Notion DB에 저장."""
    client = _get_client()
    db_id = os.environ["NOTION_WEEKLY_DB_ID"]
    title = f"[Weekly] {week_label} Automotive/AI Semiconductor 주간 보고서"

    blocks: list[dict] = []
    meta = f"일별 분석 {analysis.get('daily_count', 0)}개 취합  |  모델: {analysis.get('model', '-')}"
    blocks.extend(_paragraph_blocks(meta))
    blocks.append(_divider_block())

    sections = analysis.get("sections", {})
    if sections:
        for title_s, content in sections.items():
            blocks.append(_heading2_block(title_s))
            blocks.extend(_paragraph_blocks(content))
    else:
        blocks.extend(_paragraph_blocks(analysis.get("raw", "")))

    first_batch = blocks[:100]
    today = datetime.utcnow().strftime("%Y-%m-%d")

    page = client.pages.create(
        parent={"database_id": db_id},
        properties={
            "Name": {"title": _rich_text(title)},
            "Date": {"date": {"start": today}},
            "Type": {"select": {"name": "Weekly"}},
        },
        children=first_batch,
    )

    page_id = page["id"]
    page_url = page.get("url", "")

    remaining = blocks[100:]
    for i in range(0, len(remaining), 100):
        client.blocks.children.append(
            block_id=page_id,
            children=remaining[i : i + 100],
        )

    logger.info("Notion Weekly 페이지 생성 완료: %s", page_url)
    return page_url


def fetch_weekly_analyses(days: int = 7) -> list[dict]:
    """
    Daily DB에서 최근 N일간 분석 결과 목록 조회.
    Notion 페이지의 raw 텍스트(plain_text)를 반환.
    """
    from datetime import timedelta

    client = _get_client()
    db_id = os.environ["NOTION_DAILY_DB_ID"]
    cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")

    results = []
    cursor = None
    while True:
        kwargs = {
            "database_id": db_id,
            "filter": {
                "and": [
                    {"property": "Date", "date": {"on_or_after": cutoff}},
                    {"property": "Type", "select": {"equals": "Daily"}},
                ]
            },
            "sorts": [{"property": "Date", "direction": "ascending"}],
        }
        if cursor:
            kwargs["start_cursor"] = cursor
        resp = client.databases.query(**kwargs)
        results.extend(resp["results"])
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")

    logger.info("Notion에서 %d개 Daily 페이지 조회", len(results))

    analyses = []
    for page in results:
        date_prop = page["properties"].get("Date", {}).get("date", {})
        date_str = date_prop.get("start", "") if date_prop else ""
        # 페이지 블록 텍스트 수집
        raw_text = _extract_page_text(client, page["id"])
        analyses.append({"date": date_str, "raw": raw_text, "article_count": 0})

    return analyses


def _extract_page_text(client: Client, page_id: str) -> str:
    """페이지 블록에서 plain text 추출."""
    lines = []
    cursor = None
    while True:
        kwargs = {"block_id": page_id}
        if cursor:
            kwargs["start_cursor"] = cursor
        resp = client.blocks.children.list(**kwargs)
        for block in resp["results"]:
            btype = block.get("type", "")
            rich = block.get(btype, {}).get("rich_text", [])
            text = "".join(r.get("plain_text", "") for r in rich)
            if text:
                lines.append(text)
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")
    return "\n".join(lines)
