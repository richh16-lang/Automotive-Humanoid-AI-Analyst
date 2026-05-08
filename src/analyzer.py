"""LLM 라우터를 통해 수집된 뉴스를 10가지 양식으로 분석합니다."""
import logging
import re
from datetime import datetime

from .collector import Article
from .llm_router import call_llm

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """당신은 Automotive/AI 반도체 및 스토리지 분야의 수석 전략 분석가입니다.
SDV, 자율주행, 휴머노이드 로봇, AI 반도체, 메모리/스토리지 시장을 전문으로 합니다.
수집된 뉴스를 분석하여 아래 10개 섹션으로 정확하고 날카로운 인사이트 보고서를 작성하세요.
- 각 섹션은 ## 헤딩으로 구분하세요.
- 핵심만 간결하게 서술하되, 구체적 수치와 기업명을 포함하세요.
- 불확실한 내용은 추정임을 명시하고, 근거 없는 내용은 포함하지 마세요.
- 한국어로 작성하세요."""

ANALYSIS_TEMPLATE = """\
아래 뉴스 기사들을 분석하여 정확히 10개 섹션으로 보고서를 작성하세요.

## 1. 핵심 요약
오늘 가장 중요한 뉴스 3가지를 각각 1줄로 요약하세요.
각 항목 끝에 반드시 출처 URL을 [링크] 형태로 표기하세요.
기술적 관점과 비즈니스 관점을 모두 포함하세요.

## 2. 기술적 의미
기존 기술(Legacy) 대비 무엇이 달라졌는지 분석하세요.
- 기술적 진보 수준 (점진적 개선인가 / 패러다임 전환인가)
- 핵심 기술 변화 포인트 (아키텍처, 인터페이스, 전력, 성능)
- 실현 가능성 및 양산 시점 예측

## 3. AI Agent 아키텍처
On-device AI와 Cloud AI 에이전트 구조의 변화를 추적하세요.
- On-device 처리 vs Cloud 오프로드 비율 변화
- Agentic AI / Physical AI 관점의 아키텍처 시사점
- KV Cache, 컨텍스트 길이, 추론 방식의 변화

## 4. 비즈니스 영향
- 관련 기업의 시장 점유율 변화 가능성
- 신규 비즈니스 모델(Monetization) 기회
- 단기 수혜 기업 vs 위협받는 기업 구분

## 5. Ecosystem 영향
- OEM(완성차), Tier 1(보쉬/콘티넨탈 등), SoC 설계사, ODM 간 주도권 변화
- 새로운 협력/경쟁 구도 형성 여부
- 표준화(AUTOSAR, SOAFEE 등) 및 플랫폼 잠금(Lock-in) 동향

## 6. 향후 전망
- 단기(1년): 주요 제품 출시, 계약, 인증 일정
- 중장기(3~5년): 시장 파급력 및 기술 성숙도 예측
- 불확실성 요인(규제, 경쟁, 기술 장벽)

## 7. 메모리/스토리지 영향
- HBM, LPDDR5x, UFS, SSD 등 부품별 수요 변화
- 용량, 대역폭, 지연시간(Latency) 요구사항 변화
- 삼성전자, SK하이닉스, 마이크론 등 메모리 업체 영향

## 8. 스토리지 Workload
- AI 모델 로딩, 컨텍스트 저장, 추론 캐시 관점의 읽기/쓰기 패턴
- 데이터 로깅(블랙박스, 사고분석) 워크로드 특성
- 읽기/쓰기 빈도 변화 및 SSD/UFS 수명(TBW) 영향
- Sequential vs Random I/O 비율 추정

## 9. 지역별 영향
- 미국: 설계·IP 관점 (NVIDIA, Qualcomm, 인텔 파운드리)
- 중국: 공급망·자체개발 관점 (화웨이, BYD, CXMT)
- 한국: 메모리·스토리지 관점 (삼성, SK하이닉스)
- 유럽: 규제·안전 관점 (UN-R155, ISO 26262, CSMS)

## 10. Why Now?
왜 지금 이 뉴스가 중요한지 전략적 시급성을 평가하세요.
- 타이밍의 의미 (시장 사이클, 경쟁 압력, 규제 마감)
- 지금 당장 주목해야 할 신호(Signal) vs 노이즈(Noise) 구분
- 분석가 관점의 핵심 액션 아이템 1~2개

---
분석할 뉴스 기사 ({count}건):
{articles_text}
"""

WEEKLY_TEMPLATE = """\
지난 한 주간 일별 보고서를 종합하여 Weekly 전략 보고서를 작성하세요.

## 1. 이번 주 핵심 테마
## 2. 기술 트렌드 주간 요약
## 3. AI Agent/Physical AI 동향
## 4. 메모리·스토리지 시장 신호
## 5. SDV/자율주행 주간 흐름
## 6. 휴머노이드·로봇 주간 동향
## 7. Ecosystem 주도권 변화
## 8. 지역별 주간 동향 (미국/중국/한국/유럽)
## 9. 다음 주 Watch List (3개 이내)
## 10. 주간 전략 결론 및 권고사항

---
일별 보고서 ({count}개):
{combined}
"""


def _format_articles(articles: list[Article]) -> str:
    parts = []
    for i, a in enumerate(articles, 1):
        pub = a.published.strftime("%Y-%m-%d %H:%M UTC") if a.published else "날짜 미상"
        body = a.full_text or a.summary or "(본문 없음)"
        parts.append(
            f"[{i}] {a.source} | {pub}\n"
            f"제목: {a.title}\n"
            f"URL: {a.url}\n"
            f"키워드: {', '.join(a.matched_keywords)}\n"
            f"내용: {body[:2000]}\n"
        )
    return "\n---\n".join(parts)


def _parse_sections(text: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    matches = list(re.finditer(r"^##\s+(.+)$", text, re.MULTILINE))
    for i, m in enumerate(matches):
        title = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections[title] = text[start:end].strip()
    return sections


def analyze_articles(
    articles: list[Article],
    date_str: str | None = None,
) -> dict:
    if not articles:
        logger.warning("분석할 기사가 없습니다.")
        return {"error": "수집된 기사 없음", "raw": "", "date": date_str or ""}

    date_str = date_str or datetime.utcnow().strftime("%Y-%m-%d")
    articles_text = _format_articles(articles)
    user_content = ANALYSIS_TEMPLATE.format(
        count=len(articles),
        articles_text=articles_text,
    )

    logger.info("LLM 분석 시작 (기사: %d건)", len(articles))
    raw_text, provider = call_llm(SYSTEM_PROMPT, user_content)
    logger.info("분석 완료 (provider: %s)", provider)

    return {
        "date": date_str,
        "article_count": len(articles),
        "provider": provider,
        "raw": raw_text,
        "sections": _parse_sections(raw_text),
        "sources": list({a.source for a in articles}),
        "keywords_found": list({kw for a in articles for kw in a.matched_keywords}),
    }


def analyze_weekly(daily_analyses: list[dict]) -> dict:
    combined = "\n\n===\n\n".join(
        f"[{d.get('date', 'N/A')}] (provider: {d.get('provider', '-')})\n{d.get('raw', '')}"
        for d in daily_analyses
    )
    user_content = WEEKLY_TEMPLATE.format(
        count=len(daily_analyses),
        combined=combined[:15000],
    )

    logger.info("Weekly LLM 분석 시작 (일별 %d개)", len(daily_analyses))
    raw_text, provider = call_llm(SYSTEM_PROMPT, user_content)
    logger.info("Weekly 분석 완료 (provider: %s)", provider)

    return {
        "type": "weekly",
        "raw": raw_text,
        "sections": _parse_sections(raw_text),
        "daily_count": len(daily_analyses),
        "provider": provider,
    }
