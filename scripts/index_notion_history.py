"""
기존 Notion 데이터 일괄 인덱싱 스크립트 (1회 실행용).
최근 N일치 Notion 보고서를 Qdrant에 일괄 적재합니다.

실행 방법:
  cd news-analyzer
  python scripts/index_notion_history.py          # 기본 60일
  python scripts/index_notion_history.py --days 90
"""
import argparse
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 프로젝트 루트를 파이썬 경로에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("index_history")

KST = timezone(timedelta(hours=9))


def main() -> None:
    parser = argparse.ArgumentParser(description="Notion 보고서 → Qdrant 일괄 인덱싱")
    parser.add_argument("--days", type=int, default=60, help="소급 일수 (기본 60일)")
    parser.add_argument("--delay", type=float, default=1.0,
                        help="Gemini 임베딩 Rate Limit 대응 대기(초, 기본 1.0)")
    args = parser.parse_args()

    # 환경변수 확인
    if not os.environ.get("QDRANT_URL"):
        logger.error("QDRANT_URL 환경변수가 없습니다. .env 파일을 확인하세요.")
        sys.exit(1)
    if not os.environ.get("GEMINI_API_KEY"):
        logger.error("GEMINI_API_KEY 환경변수가 없습니다.")
        sys.exit(1)

    from src.notion_client import fetch_daily_from_notion
    from src.vector_store import index_daily_report

    today    = datetime.now(KST).date()
    success  = 0
    skipped  = 0
    failed   = 0

    logger.info("=== Notion → Qdrant 일괄 인덱싱 시작 (최근 %d일) ===", args.days)

    for days_ago in range(0, args.days):
        target_date = today - timedelta(days=days_ago)
        date_str    = target_date.strftime("%Y-%m-%d")

        try:
            analysis = fetch_daily_from_notion(date_str)

            if not analysis or not analysis.get("sections"):
                logger.info("[%s] Notion 데이터 없음 — 건너뜀", date_str)
                skipped += 1
                continue

            indexed = index_daily_report(analysis)
            if indexed > 0:
                logger.info("[%s] ✅ %d개 섹션 인덱싱 완료", date_str, indexed)
                success += 1
            else:
                logger.warning("[%s] 인덱싱된 섹션 0개", date_str)
                skipped += 1

            time.sleep(args.delay)  # Gemini 임베딩 Rate Limit 대응

        except Exception as e:
            logger.error("[%s] ❌ 실패: %s", date_str, e)
            failed += 1
            time.sleep(args.delay * 2)

    logger.info("=== 완료: 성공 %d일 / 건너뜀 %d일 / 실패 %d일 ===",
                success, skipped, failed)


if __name__ == "__main__":
    main()
