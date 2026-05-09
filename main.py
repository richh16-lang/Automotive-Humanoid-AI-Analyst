"""
Daily 파이프라인 — 전략 의사결정 지원 시스템.

파이프라인:
  1. 뉴스 수집 (RSS + Google News + Arxiv + SemiWiki)
  2. Groq 고속 필터링 (관련 없는 뉴스 제거, 우선순위 결정)
  3. Gemini 배경 조사 (사실 검증 + 기술 맥락 보강, 무료 티어 Rate Limit 준수)
  4. Claude/DeepSeek 앙상블 합성 (10섹션 분석, 출처 링크 + AI 기여 모델 표기)
  5. 결과 저장: Notion DB | Markdown(NotebookLM용) | PPT(템플릿 기반) | Gmail(PPT 첨부)
"""
import logging
import os
import sys
from datetime import datetime, timezone
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
MD_OUTPUT_DIR  = os.environ.get("MD_OUTPUT_DIR",  PPT_OUTPUT_DIR)


def run_daily() -> int:
    from src.collector       import run_collection
    from src.groq_filter     import filter_and_rank
    from src.gemini_researcher import research_articles
    from src.analyzer        import analyze_articles
    from src.markdown_exporter import generate_markdown
    from src.ppt_generator   import generate_ppt
    from src.notion_client   import save_daily_to_notion
    from src.email_sender    import send_daily_email

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    logger.info("====== Daily Pipeline 시작: %s ======", date_str)

    # ── 1. 뉴스 수집 ─────────────────────────────────────────
    try:
        articles = run_collection(hours=26)
        logger.info("수집 완료: %d건", len(articles))
    except Exception as e:
        logger.exception("수집 실패: %s", e)
        return 1

    if not articles:
        logger.warning("수집된 기사 없음. 종료.")
        return 0

    # ── 2. Groq 고속 필터링 ──────────────────────────────────
    try:
        articles, filter_meta = filter_and_rank(articles, top_n=30, min_score=4)
        logger.info("Groq 필터링 결과: %d건 → %d건",
                    filter_meta["original_count"], filter_meta["filtered_count"])
    except Exception as e:
        logger.warning("Groq 필터링 실패 (전체 기사 사용): %s", e)
        filter_meta = {"used_groq": False, "original_count": len(articles),
                       "filtered_count": len(articles), "scores": []}

    if not articles:
        logger.warning("필터링 후 기사 없음. 종료.")
        return 0

    # ── 3. Gemini 배경 조사 ───────────────────────────────────
    try:
        articles, research_meta = research_articles(articles, max_articles=15)
        logger.info("Gemini 조사 완료: %d건 처리", research_meta.get("researched_count", 0))
    except Exception as e:
        logger.warning("Gemini 조사 실패 (원본 기사 사용): %s", e)
        research_meta = {"used_gemini": False}

    # ── 4. 앙상블 합성 분석 ───────────────────────────────────
    try:
        analysis = analyze_articles(
            articles,
            date_str=date_str,
            filter_meta=filter_meta,
            research_meta=research_meta,
        )
        logger.info("분석 완료 | 모델: %s", analysis.get("model_attribution", "-"))
    except Exception as e:
        logger.exception("LLM 분석 실패: %s", e)
        return 1

    # ── 5a. Markdown 생성 (NotebookLM용) ────────────────────
    md_path = None
    try:
        md_path = generate_markdown(analysis, output_dir=MD_OUTPUT_DIR)
        logger.info("Markdown 생성 완료: %s", md_path)
    except Exception as e:
        logger.warning("Markdown 생성 실패 (계속 진행): %s", e)

    # ── 5b. PPT 생성 (템플릿 기반) ──────────────────────────
    ppt_path = None
    try:
        ppt_path = generate_ppt(analysis, output_dir=PPT_OUTPUT_DIR)
        logger.info("PPT 생성 완료: %s", ppt_path)
    except Exception as e:
        logger.warning("PPT 생성 실패 (계속 진행): %s", e)

    # ── 5c. Notion 저장 ───────────────────────────────────────
    try:
        notion_url = save_daily_to_notion(analysis)
        analysis["notion_url"] = notion_url
        logger.info("Notion 저장 완료: %s", notion_url)
    except Exception as e:
        logger.warning("Notion 저장 실패 (계속 진행): %s", e)

    # ── 5d. Gmail 발송 (PPT + MD 첨부) ──────────────────────
    try:
        attachments = [p for p in [ppt_path, md_path] if p]
        send_daily_email(analysis, ppt_path=ppt_path, extra_attachments=attachments)
    except TypeError:
        # email_sender가 extra_attachments를 아직 지원 안 할 경우
        try:
            send_daily_email(analysis, ppt_path=ppt_path)
        except Exception as e2:
            logger.exception("이메일 발송 실패: %s", e2)
            return 1
    except Exception as e:
        logger.exception("이메일 발송 실패: %s", e)
        return 1

    logger.info("====== Daily Pipeline 완료 ======")
    logger.info("  분석 모델: %s", analysis.get("model_attribution", "-"))
    logger.info("  기사 수: %d건", analysis.get("article_count", 0))
    logger.info("  PPT: %s", ppt_path or "생성 안 됨")
    logger.info("  Markdown: %s", md_path or "생성 안 됨")
    logger.info("  Notion: %s", analysis.get("notion_url", "저장 안 됨"))
    return 0


if __name__ == "__main__":
    sys.exit(run_daily())
