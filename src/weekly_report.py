"""Weekly 보고서 생성 파이프라인."""
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def get_week_label() -> str:
    today  = datetime.utcnow().date()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    week   = today.isocalendar()[1]
    return f"{today.year}-W{week:02d} ({monday.strftime('%m/%d')}~{sunday.strftime('%m/%d')})"


def run_weekly_pipeline() -> None:
    from . import analyzer as _analyzer
    from . import notion_client as _notion
    from . import email_sender as _email
    from .ppt_generator import generate_ppt
    import os

    week_label = get_week_label()
    logger.info("=== Weekly 보고서 시작: %s ===", week_label)

    daily_analyses = _notion.fetch_weekly_analyses(days=7)
    if not daily_analyses:
        logger.warning("최근 7일 Daily 데이터 없음.")
        return

    weekly = _analyzer.analyze_weekly(daily_analyses)
    weekly["date"] = datetime.utcnow().strftime("%Y-%m-%d")
    weekly["week_label"] = week_label

    # PPT 생성
    ppt_path = None
    try:
        ppt_output = os.environ.get("PPT_OUTPUT_DIR", "/tmp")
        ppt_path = generate_ppt(weekly, output_dir=ppt_output)
        logger.info("Weekly PPT 생성: %s", ppt_path)
    except Exception as e:
        logger.warning("Weekly PPT 생성 실패: %s", e)

    notion_url = _notion.save_weekly_to_notion(weekly, week_label)
    weekly["notion_url"] = notion_url

    _email.send_weekly_email(weekly, week_label, ppt_path=ppt_path)
    logger.info("=== Weekly 보고서 완료: %s ===", week_label)
