"""Claude API를 이용해 수집된 뉴스를 10가지 양식으로 분석합니다."""
import logging
import os
from datetime import datetime

import anthropic

from .collector import Article

logger = logging.getLogger(__name__)

# 분석 결과 타입
AnalysisResult = dict  # {section_title: str, content: str, ...}

SYSTEM_PROMPT = """당신은 Automotive/AI 반도체 분야의 수석 전략 분석가입니다.
수집된 뉴스 기사들을 분석하여 아래 10가지 섹션으로 구성된 정확하고 날카로운 인사이트 보고서를 작성하세요.
각 섹션은 마크다운 헤딩(##)으로 구분하고, 핵심만 간결하게 서술하세요.
불확실한 정보는 추정임을 명시하고, 근거 없는 내용은 포함하지 마세요."""

ANALYSIS_TEMPLATE = """다음 뉴스 기사들을 분석하여 10가지 섹션으로 보고서를 작성하세요.

## 1. 핵심 요약 (Key Highlights)
- 오늘 가장 중요한 뉴스 3~5개를 bullet point로 요약

## 2. SoC 영향 분석 (SoC Impact)
- 관련 SoC 벤더(Qualcomm, NVIDIA, Mobileye, Renesas, NXP, STMicro 등) 동향
- 신규 칩 발표, 설계 수주, 경쟁 구도 변화

## 3. HBM/스토리지 워크로드 영향 (Memory & Storage Workload)
- HBM, LPDDR, NAND 수요에 미치는 영향
- AI/추론 워크로드 변화와 메모리 bandwidth 요구사항

## 4. SDV/자동차 전장 동향 (SDV & Automotive Electronics)
- Software Defined Vehicle 아키텍처 변화
- OEM·Tier1·반도체 업체 전략 변화

## 5. 휴머노이드/로봇 동향 (Humanoid & Robotics)
- 주요 기업(Tesla, Figure, Boston Dynamics 등) 개발 현황
- 반도체 수요 시사점

## 6. 공급망 및 파트너십 (Supply Chain & Partnerships)
- 신규 계약, JV, 공급망 재편 동향
- TSMC·삼성·인텔 파운드리 관련 뉴스

## 7. 경쟁 구도 변화 (Competitive Landscape)
- 시장 점유율, 포지셔닝 변화
- 주목할 신규 진입자 또는 철수 동향

## 8. 투자·M&A 동향 (Investment & M&A)
- 주요 펀딩, 인수합병, 전략적 투자
- 밸류에이션 및 시장 온도

## 9. 규제·정책 시사점 (Regulatory & Policy)
- 각국 반도체·자동차 정책 변화
- 수출통제, 보조금, 안전 규제 동향

## 10. 전략적 권고사항 (Strategic Recommendations)
- 분석가 관점의 핵심 액션 아이템 (3개 이내)
- 단기(1~3개월) 주목 포인트

---
분석할 뉴스 기사:
{articles_text}
"""


def _format_articles_for_prompt(articles: list[Article]) -> str:
    parts = []
    for i, art in enumerate(articles, 1):
        pub = art.published.strftime("%Y-%m-%d %H:%M UTC") if art.published else "날짜 미상"
        body = art.full_text or art.summary or "(본문 없음)"
        parts.append(
            f"[기사 {i}] {art.source} | {pub}\n"
            f"제목: {art.title}\n"
            f"URL: {art.url}\n"
            f"키워드: {', '.join(art.matched_keywords)}\n"
            f"내용: {body}\n"
        )
    return "\n---\n".join(parts)


def analyze_articles(
    articles: list[Article],
    model: str | None = None,
    date_str: str | None = None,
) -> dict:
    """
    Claude API로 기사 분석 후 결과 dict 반환.
    prompt caching으로 system prompt 재사용 비용 절감.
    """
    if not articles:
        logger.warning("분석할 기사가 없습니다.")
        return {"error": "수집된 기사 없음", "raw": "", "date": date_str or ""}

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    model = model or os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
    date_str = date_str or datetime.utcnow().strftime("%Y-%m-%d")

    articles_text = _format_articles_for_prompt(articles)
    user_content = ANALYSIS_TEMPLATE.format(articles_text=articles_text)

    logger.info("Claude API 분석 시작 (모델: %s, 기사: %d건)", model, len(articles))

    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},  # prompt caching
            }
        ],
        messages=[{"role": "user", "content": user_content}],
    )

    raw_text = response.content[0].text
    logger.info(
        "분석 완료 | 입력 토큰: %d (캐시 히트: %d) | 출력 토큰: %d",
        response.usage.input_tokens,
        getattr(response.usage, "cache_read_input_tokens", 0),
        response.usage.output_tokens,
    )

    sections = _parse_sections(raw_text)
    return {
        "date": date_str,
        "article_count": len(articles),
        "model": model,
        "raw": raw_text,
        "sections": sections,
        "sources": list({a.source for a in articles}),
        "keywords_found": list({kw for a in articles for kw in a.matched_keywords}),
    }


def _parse_sections(text: str) -> dict[str, str]:
    """마크다운 ## 헤딩 기준으로 섹션 분리."""
    import re
    sections: dict[str, str] = {}
    pattern = re.compile(r"^##\s+(.+)$", re.MULTILINE)
    matches = list(pattern.finditer(text))
    for i, m in enumerate(matches):
        title = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections[title] = text[start:end].strip()
    return sections


def analyze_weekly(daily_analyses: list[dict], model: str | None = None) -> dict:
    """
    한 주간 daily 분석 결과를 받아 Weekly 요약 보고서 생성.
    """
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    model = model or os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")

    combined = "\n\n===\n\n".join(
        f"[{d.get('date', 'N/A')}] 기사 {d.get('article_count', 0)}건\n{d.get('raw', '')}"
        for d in daily_analyses
    )

    weekly_prompt = f"""지난 한 주간의 일별 분석 보고서를 종합하여 Weekly 전략 보고서를 작성하세요.

## 1. 이번 주 핵심 테마 (Top Themes of the Week)
## 2. SoC/반도체 주간 주요 동향
## 3. SDV/자동차 전장 주간 흐름
## 4. 휴머노이드·로봇 주간 동향
## 5. HBM·메모리 시장 신호
## 6. 공급망 및 투자 주간 리뷰
## 7. 다음 주 주목 포인트 (Watch List)
## 8. 주간 전략 결론

---
일별 보고서:
{combined[:15000]}
"""

    logger.info("Weekly 분석 시작 (일별 데이터 %d개)", len(daily_analyses))
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": weekly_prompt}],
    )

    raw_text = response.content[0].text
    return {
        "type": "weekly",
        "raw": raw_text,
        "sections": _parse_sections(raw_text),
        "daily_count": len(daily_analyses),
        "model": model,
    }
