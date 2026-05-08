"""Daily 파이프라인: 수집 → 분석 → PPT 생성 → Notion 저장 → Gmail 발송."""
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("main")

PPT_OUTPUT_DIR = os.environ.get("PPT_OUTPUT_DIR", "/tmp")


def run_daily() -> int:
    from src.collector import run_collection
    from src.analyzer import analyze_articles
    from src.ppt_generator import generate_ppt
    from src.notion_client import save_daily_to_notion
    from src.email_sender import send_daily_email

    date_str = datetime.utcnow().strftime("%Y-%m-%d")
    logger.info("====== Daily Pipeline 시작: %s ======", date_str)

    # 1. 뉴스 수집
    try:
        articles = run_collection(hours=26)
    except Exception as e:
        logger.exception("수집 실패: %s", e)
        return 1

    if not articles:
        logger.warning("수집된 기사 없음. 종료.")
        return 0

    # 2. LLM 분석 (Claude → Gemini → GPT 자동 폴백)
    try:
        analysis = analyze_articles(articles, date_str=date_str)
    except Exception as e:
        logger.exception("LLM 분석 실패: %s", e)
        return 1

    # 3. PPT 생성
    ppt_path = None
    try:
        ppt_path = generate_ppt(analysis, output_dir=PPT_OUTPUT_DIR)
        logger.info("PPT 생성 완료: %s", ppt_path)
    except Exception as e:
        logger.warning("PPT 생성 실패 (계속 진행): %s", e)

    # 4. Notion 저장
    try:
        notion_url = save_daily_to_notion(analysis)
        analysis["notion_url"] = notion_url
    except Exception as e:
        logger.warning("Notion 저장 실패 (계속 진행): %s", e)

    # 5. Gmail 발송 (PPT 첨부)
    try:
        send_daily_email(analysis, ppt_path=ppt_path)
    except Exception as e:
        logger.exception("이메일 발송 실패: %s", e)
        return 1

    logger.info("====== Daily Pipeline 완료 ======")
    return 0


if __name__ == "__main__":
    sys.exit(run_daily())
