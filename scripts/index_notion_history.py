"""
기존 Notion 데이터 일괄 인덱싱 스크립트 (1회 실행용).
Notion DB의 모든 Daily 보고서를 직접 나열하여 Qdrant에 적재합니다.

실행 방법:
  cd C:\Users\User\news-analyzer
  pip install qdrant-client
  python scripts/index_notion_history.py
"""
import logging
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("index_history")

_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _list_all_pages() -> list[tuple[str, str]]:
    """
    Notion DB의 모든 Daily 페이지를 나열.
    반환값: [(date_str, page_id), ...]  — 날짜 오래된 순
    """
    import requests as _req

    db_id  = os.environ["NOTION_DAILY_DB_ID"].strip()
    token  = os.environ["NOTION_TOKEN"].strip()
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }

    pages  = []
    cursor = None

    while True:
        body: dict = {"page_size": 100, "sorts": [{"timestamp": "created_time", "direction": "descending"}]}
        if cursor:
            body["start_cursor"] = cursor

        resp = _req.post(
            f"https://api.notion.com/v1/databases/{db_id}/query",
            headers=headers, json=body, timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()

        for page in data.get("results", []):
            page_id = page["id"]
            # 제목에서 날짜 추출
            title_parts = (
                page.get("properties", {})
                    .get("이름", {})
                    .get("title", [])
            )
            title = "".join(t.get("plain_text", "") for t in title_parts)
            m = _DATE_RE.search(title)
            if m:
                pages.append((m.group(1), page_id))

        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")

    # 오래된 날짜부터 인덱싱 (역순 정렬)
    pages.sort(key=lambda x: x[0])
    return pages


def main() -> None:
    for var in ("QDRANT_URL", "QDRANT_API_KEY", "GEMINI_API_KEY",
                "NOTION_TOKEN", "NOTION_DAILY_DB_ID"):
        if not os.environ.get(var):
            logger.error("%s 환경변수 없음. .env 파일 확인", var)
            sys.exit(1)

    from src.notion_client import fetch_daily_from_notion
    from src.vector_store import index_daily_report

    logger.info("=== Notion DB 페이지 목록 조회 중 ===")
    pages = _list_all_pages()
    logger.info("총 %d개 페이지 발견", len(pages))

    success = skipped = failed = 0

    for date_str, page_id in pages:
        try:
            analysis = fetch_daily_from_notion(date_str)

            if not analysis or not analysis.get("sections"):
                logger.info("[%s] 섹션 없음 — 건너뜀", date_str)
                skipped += 1
                continue

            # date가 없으면 title에서 추출한 날짜로 보완
            if not analysis.get("date"):
                analysis["date"] = date_str

            indexed = index_daily_report(analysis)
            if indexed > 0:
                logger.info("[%s] ✅ %d개 섹션 인덱싱 완료", date_str, indexed)
                success += 1
            else:
                logger.warning("[%s] 인덱싱된 섹션 0개", date_str)
                skipped += 1

            time.sleep(1.5)  # Gemini Rate Limit 대응

        except Exception as e:
            logger.error("[%s] ❌ 실패: %s", date_str, e)
            failed += 1
            time.sleep(3)

    logger.info("=== 완료: 성공 %d / 건너뜀 %d / 실패 %d ===", success, skipped, failed)


if __name__ == "__main__":
    main()
