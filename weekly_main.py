"""Weekly 보고서 생성 진입점."""
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("weekly_main")


def run_weekly() -> int:
    try:
        from src.weekly_report import run_weekly_pipeline
        run_weekly_pipeline()
        return 0
    except Exception as e:
        logger.exception("Weekly 파이프라인 오류: %s", e)
        return 1


if __name__ == "__main__":
    sys.exit(run_weekly())
