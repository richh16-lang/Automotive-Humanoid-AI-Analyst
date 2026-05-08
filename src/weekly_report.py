"""Weekly 보고서 생성 파이프라인."""
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def get_week_label() -> str:
    """이번 주 라벨 반환 예: '2026-W19 (05/04~05/10)'"""
    today = datetime.utcnow().date()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    week_num = today.isocalendar()[1]
    year = today.year
    return f"{year}-W{week_num:02d} ({monday.strftime('%m/%d')}~{sunday.strftime('%m/%d')})"


def run_weekly_pipeline() -> None:
    """
    1. Notion Daily DB에서 최근 7일 분석 조회
    2. Claude API로 Weekly 요약 생성
    3. Notion Weekly DB에 저장
    4. Gmail로 발송
    """
    from . import analyzer as _analyzer
    from . import notion_client as _notion
    from . import email_sender as _email

    week_label = get_week_label()
    logger.info("=== Weekly 보고서 생성 시작: %s ===", week_label)

    # 1. Notion에서 지난 7일 Daily 분석 불러오기
    daily_analyses = _notion.fetch_weekly_analyses(days=7)
    if not daily_analyses:
        logger.warning("최근 7일간 Daily 분석 데이터가 없습니다.")
        return

    # 2. Claude로 Weekly 분석
    weekly_result = _analyzer.analyze_weekly(daily_analyses)

    # 3. Notion에 저장
    notion_url = _notion.save_weekly_to_notion(weekly_result, week_label)
    weekly_result["notion_url"] = notion_url

    # 4. 이메일 발송
    _email.send_weekly_email(weekly_result, week_label)

    logger.info("=== Weekly 보고서 완료: %s ===", week_label)
