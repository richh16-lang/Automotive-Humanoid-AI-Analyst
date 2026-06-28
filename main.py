"""
Daily 파이프라인 — 전략 의사결정 지원 시스템.

파이프라인:
  1. 뉴스 수집 (RSS + Google News + Arxiv + SemiWiki)
  2. Groq 고속 필터링 (관련 없는 뉴스 제거, 우선순위 결정)
  3. Gemini 배경 조사 (사실 검증 + 기술 맥락 보강, 무료 티어 Rate Limit 준수)
  4. Claude/DeepSeek 앙상블 합성 (10섹션 분석)
  5. 결과 저장:
     - Notion DB (이미지·테이블·차트 포함)
     - Word 보고서 (.docx, 차트 임베딩 — PPT 수작업 제작용)
     - Markdown (.md, NotebookLM용)
     - Gmail (Word + MD 첨부)
"""
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("main")

OUTPUT_DIR = os.environ.get("PPT_OUTPUT_DIR",
             os.environ.get("OUTPUT_DIR", "/tmp"))
MD_OUTPUT_DIR = os.environ.get("MD_OUTPUT_DIR", OUTPUT_DIR)


def run_daily() -> int:
    from src.collector         import run_collection
    from src.groq_filter       import filter_and_rank
    from src.gemini_researcher import research_articles
    from src.analyzer          import analyze_articles
    from src.markdown_exporter import generate_markdown
    from src.word_exporter     import generate_word
    from src.notion_client     import save_daily_to_notion
    from src.email_sender      import send_daily_email

    date_str = datetime.now(KST).strftime("%Y-%m-%d")
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
        logger.info("Groq 필터링: %d건 → %d건",
                    filter_meta["original_count"], filter_meta["filtered_count"])
    except Exception as e:
        logger.warning("Groq 필터링 실패 (전체 기사 사용): %s", e)
        filter_meta = {"used_groq": False, "original_count": len(articles),
                       "filtered_count": len(articles), "scores": []}

    if not articles:
        logger.warning("필터링 후 기사 없음. 종료.")
        return 0

    # ── 2.5. 엔티티 언급량 추적 ─────────────────────────────────
    spike_report, spike_entities = "", []
    try:
        from src.entity_tracker import run_entity_tracking
        spike_report, spike_entities = run_entity_tracking(articles, date_str)
        if spike_report:
            logger.info("언급량 급증 감지: %s", ", ".join(spike_entities))
    except Exception as e:
        logger.warning("Entity Tracker 실패 (계속 진행): %s", e)

    # ── 3. Gemini 배경 조사 ───────────────────────────────────
    try:
        articles, research_meta = research_articles(articles, max_articles=15,
                                                    spike_entities=spike_entities)
        logger.info("Gemini 조사 완료: %d건", research_meta.get("researched_count", 0))
    except Exception as e:
        logger.warning("Gemini 조사 실패 (원본 기사 사용): %s", e)
        research_meta = {"used_gemini": False}

    # ── 3.5. Qdrant 기억 조회 ────────────────────────────────
    memory_context = ""
    try:
        from src.vector_store import build_memory_context
        articles_summary = " ".join(
            f"{a.title} {' '.join(a.matched_keywords)}"
            for a in articles[:10]
        )
        memory_context = build_memory_context(articles_summary, date_str)
        if memory_context:
            logger.info("Qdrant 기억 조회 완료: %d자", len(memory_context))
        else:
            logger.info("Qdrant 기억 없음 (첫 실행 또는 미설정)")
    except Exception as e:
        logger.warning("Qdrant 기억 조회 실패 (계속 진행): %s", e)

    # ── 4. 앙상블 합성 분석 ───────────────────────────────────
    try:
        analysis = analyze_articles(
            articles,
            date_str=date_str,
            filter_meta=filter_meta,
            research_meta=research_meta,
            memory_context=memory_context or None,
            spike_report=spike_report or None,
        )
        logger.info("분석 완료 | 모델: %s", analysis.get("model_attribution", "-"))
    except Exception as e:
        logger.exception("LLM 분석 실패: %s", e)
        return 1

    # ── 5a. Markdown 생성 (NotebookLM용) ─────────────────────
    md_path = None
    try:
        md_path = generate_markdown(analysis, output_dir=MD_OUTPUT_DIR)
        logger.info("Markdown 생성 완료: %s", md_path)
    except Exception as e:
        logger.warning("Markdown 생성 실패 (계속 진행): %s", e)

    # ── 5b. Word 보고서 생성 (차트 포함) ─────────────────────
    word_path = None
    try:
        word_path = generate_word(analysis, output_dir=OUTPUT_DIR)
        logger.info("Word 보고서 생성 완료: %s", word_path)
    except Exception as e:
        logger.warning("Word 생성 실패 (계속 진행): %s", e)

    # ── 5c. Notion 저장 (이미지·테이블 포함) ─────────────────
    try:
        notion_url = save_daily_to_notion(analysis)
        analysis["notion_url"] = notion_url
        logger.info("Notion 저장 완료: %s", notion_url)
    except Exception as e:
        logger.warning("Notion 저장 실패 (계속 진행): %s", e)

    # ── 5e. Qdrant 인덱싱 ────────────────────────────────────
    try:
        from src.vector_store import index_daily_report
        indexed = index_daily_report(analysis)
        if indexed > 0:
            logger.info("Qdrant 인덱싱 완료: %d개 섹션", indexed)
    except Exception as e:
        logger.warning("Qdrant 인덱싱 실패 (계속 진행): %s", e)

    # ── 5d. Gmail 발송 (Word + MD 첨부) ─────────────────────
    try:
        send_daily_email(
            analysis,
            word_path=word_path,
            md_path=md_path,
        )
        logger.info("이메일 발송 완료")
    except Exception as e:
        logger.exception("이메일 발송 실패: %s", e)
        return 1

    logger.info("====== Daily Pipeline 완료 ======")
    logger.info("  분석 모델 : %s", analysis.get("model_attribution", "-"))
    logger.info("  기사 수   : %d건", analysis.get("article_count", 0))
    logger.info("  Word 보고서: %s", word_path or "생성 안 됨")
    logger.info("  Markdown  : %s", md_path or "생성 안 됨")
    logger.info("  Notion    : %s", analysis.get("notion_url", "저장 안 됨"))
    return 0


if __name__ == "__main__":
    sys.exit(run_daily())
