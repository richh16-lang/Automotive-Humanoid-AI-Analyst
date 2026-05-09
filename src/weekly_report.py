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
    from .ppt_generator    import generate_ppt
    from .markdown_exporter import generate_markdown

    ppt_output = os.environ.get("PPT_OUTPUT_DIR", "/tmp")
    md_output  = os.environ.get("MD_OUTPUT_DIR",  ppt_output)
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

    # ── PPT 생성 ─────────────────────────────────────────────
    ppt_path = None
    try:
        ppt_path = generate_ppt(weekly, output_dir=ppt_output)
        logger.info("Weekly PPT 생성: %s", ppt_path)
    except Exception as e:
        logger.warning("Weekly PPT 생성 실패: %s", e)

    # ── Notion 저장 ───────────────────────────────────────────
    try:
        notion_url = _notion.save_weekly_to_notion(weekly, week_label)
        weekly["notion_url"] = notion_url
    except Exception as e:
        logger.warning("Weekly Notion 저장 실패: %s", e)

    # ── 이메일 발송 (PPT + MD 첨부) ──────────────────────────
    attachments = [p for p in [ppt_path, md_path] if p]
    _email.send_weekly_email(weekly, week_label, ppt_path=ppt_path,
                              extra_attachments=attachments)

    logger.info("=== Weekly 보고서 완료: %s ===", week_label)
