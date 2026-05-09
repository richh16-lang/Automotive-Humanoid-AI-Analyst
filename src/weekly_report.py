"""Weekly 보고서 생성 파이프라인."""
import logging
import os
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


def get_week_label() -> str:
    today  = datetime.now(timezone.utc).date()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    week   = today.isocalendar()[1]
    return f"{today.year}-W{week:02d} ({monday.strftime('%m/%d')}~{sunday.strftime('%m/%d')})"


def run_weekly_pipeline() -> None:
    from . import analyzer as _analyzer
    from . import notion_client as _notion
    from . import email_sender as _email
    from .word_exporter     import generate_word
    from .markdown_exporter import generate_markdown

    output_dir = os.environ.get("PPT_OUTPUT_DIR",
                 os.environ.get("OUTPUT_DIR", "/tmp"))
    md_output  = os.environ.get("MD_OUTPUT_DIR", output_dir)
    week_label = get_week_label()
    logger.info("=== Weekly 보고서 시작: %s ===", week_label)

    # ── Daily 데이터 조회 ─────────────────────────────────────
    daily_analyses = _notion.fetch_weekly_analyses(days=7)
    if not daily_analyses:
        logger.warning("최근 7일 Daily 데이터 없음.")
        return

    # ── 주간 합성 분석 ────────────────────────────────────────
    weekly = _analyzer.analyze_weekly(daily_analyses)
    weekly["date"]       = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    weekly["week_label"] = week_label
    weekly["type"]       = "weekly"

    # ── Markdown 생성 (NotebookLM용) ─────────────────────────
    md_path = None
    try:
        md_path = generate_markdown(weekly, output_dir=md_output)
        logger.info("Weekly Markdown 생성: %s", md_path)
    except Exception as e:
        logger.warning("Weekly Markdown 생성 실패: %s", e)

    # ── Word 보고서 생성 (차트 포함) ──────────────────────────
    word_path = None
    try:
        word_path = generate_word(weekly, output_dir=output_dir)
        logger.info("Weekly Word 생성: %s", word_path)
    except Exception as e:
        logger.warning("Weekly Word 생성 실패: %s", e)

    # ── Notion 저장 (이미지·테이블 포함) ─────────────────────
    try:
        notion_url = _notion.save_weekly_to_notion(weekly, week_label)
        weekly["notion_url"] = notion_url
    except Exception as e:
        logger.warning("Weekly Notion 저장 실패: %s", e)

    # ── 이메일 발송 (Word + MD 첨부) ─────────────────────────
    _email.send_weekly_email(
        weekly,
        week_label,
        word_path=word_path,
        md_path=md_path,
    )

    logger.info("=== Weekly 보고서 완료: %s ===", week_label)
