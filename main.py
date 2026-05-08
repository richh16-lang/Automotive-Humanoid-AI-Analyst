"""Daily 뉴스 수집 → 분석 → Notion 저장 → Gmail 발송 파이프라인."""
import logging
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

# 프로젝트 루트의 .env 로드
load_dotenv(Path(__file__).parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("main")


def run_daily() -> int:
    """0 = 성공, 1 = 오류."""
    from src.collector import run_collection
    from src.analyzer import analyze_articles
    from src.notion_client import save_daily_to_notion
    from src.email_sender import send_daily_email

    date_str = datetime.utcnow().strftime("%Y-%m-%d")
    logger.info("====== Daily Pipeline 시작: %s ======", date_str)

    # 1. 뉴스 수집
    try:
        articles = run_collection(hours=26)
    except Exception as e:
        logger.exception("뉴스 수집 실패: %s", e)
        return 1

    if not articles:
        logger.warning("수집된 기사가 없습니다. 파이프라인 종료.")
        return 0

    # 2. Claude 분석
    try:
        analysis = analyze_articles(articles, date_str=date_str)
    except Exception as e:
        logger.exception("Claude 분석 실패: %s", e)
        return 1

    # 3. Notion 저장
    try:
        notion_url = save_daily_to_notion(analysis)
        analysis["notion_url"] = notion_url
    except Exception as e:
        logger.exception("Notion 저장 실패: %s", e)
        # Notion 실패해도 이메일은 시도
        notion_url = ""

    # 4. Gmail 발송
    try:
        send_daily_email(analysis)
    except Exception as e:
        logger.exception("이메일 발송 실패: %s", e)
        return 1

    logger.info("====== Daily Pipeline 완료 ======")
    return 0


if __name__ == "__main__":
    sys.exit(run_daily())
