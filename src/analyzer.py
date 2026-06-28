"""
전략 의사결정 지원 시스템 — 분석 엔진.
Groq 전처리 → Gemini 조사 → Claude/DeepSeek 앙상블 합성.
"""
import logging
import re
from datetime import datetime, timezone

from .collector import Article
from .llm_router import call_llm

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# 시스템 프롬프트 — 데이터 이동 효율 & 메모리 병목 관점 강화
# ══════════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """당신은 Automotive/AI 반도체 및 스토리지 분야의 수석 전략 분석가입니다.
전문 영역: SDV, 자율주행, 휴머노이드 로봇, AI 반도체, 메모리/스토리지 전략 기획.

## 핵심 분석 관점 (모든 섹션에 적용)

### 1. 데이터 이동 효율 (Data Movement Efficiency)
- AI 추론 시 데이터가 이동하는 경로 (Storage → DRAM → Cache → Compute)
- 각 계층 간 대역폭 병목 지점 식별
- PCIe Gen6, CXL, NVMe 등 인터페이스가 데이터 이동에 미치는 영향

### 2. 메모리 병목 (Memory Bottleneck)
- LLM/AI 모델의 KV Cache 크기와 메모리 요구량 변화
- Compute-to-Memory 비율 불균형 문제
- HBM vs LPDDR5x vs UFS 계층별 역할 분담

### 3. Storage Workload 수치적 추론 (필수)
- **Read/Write Ratio**: AI 추론(KV Cache Read 집약적) vs 센서 로깅(Write 집약적) 비율 추정
- **WAF (Write Amplification Factor)**: 차량 온도 변화(-40°C~+125°C) + Small Random Write가
  UFS/SSD 수명에 미치는 영향. 예: WAF 2.0 → 실효 TBW 50% 감소
- **TBW 영향**: 워크로드 특성이 제품 수명에 미치는 영향 수치화
- **Capacity Planning**: End-to-End 모델(FSD v12 등) 전환 시 로컬 스토리지 요구량 예측

## 출력 규칙
- 각 섹션: ## 헤딩으로 구분
- 출처 URL 반드시 포함: [출처: URL] 또는 [링크] 형태
- 분석에 기여한 AI 모델 표기:
  [분석: {synthesis_model} | 전처리: {filter_model} | 조사: {research_model}]
- 수치 없는 Storage Workload 분석은 불완전한 것으로 간주
- 한국어로 작성

## 데이터 출처 라벨 규칙 (섹션 8 필수 / 전 섹션 권장)
모든 수치·주장에는 반드시 아래 라벨 중 하나를 항목 끝에 표기하세요:
  📰 직접 인용  — 오늘 수집된 기사에 명시된 수치·사실 (기사명 또는 URL 병기)
  🔢 수치 추론  — 공개된 사양/표준 기반으로 계산한 추정값. 반드시 계산식 명시:
                   형식: [계산 근거: 입력값 A × 계수 B = 결과값 C, 가정: ...]
  📊 시장 추정치 — 업계 컨센서스·리서치 보고서 기반 추정 (출처 기관명 명시)

⚠️ 라벨 없는 수치는 작성 금지. 추론·추정인 경우 계산 근거 생략 불가.

## 출력 포맷 (반드시 준수)
- 모든 불릿 항목 앞에 문맥에 맞는 이모지 필수:
  🚀 기술 혁신/제품 출시 | ⚠️ 위험/지연/리스크 | 🏢 기업 동향 | 🛠️ 아키텍처/기술 구조
  📈 시장 성장 | 📉 하락/부정 | 💡 전략적 시사점 | 🌍 지역별 동향 | ⚙️ 제품/사양
- 각 항목의 핵심 주제는 **[키워드]** 형식으로 앞에 배치 (반드시 - 불릿 마커 유지):
  예) - 🚀 **[NVIDIA DRIVE Thor]** Thor SoC 기반 차량용 플랫폼이...
  예) - ⚠️ **[HBM3E 인증 지연]** 삼성전자의 NVIDIA 납기 리스크 확대...
  예) - 🏢 **[SK하이닉스]** HBM 시장 주도권 유지하며..."""

# ══════════════════════════════════════════════════════════════════════════════
# 10섹션 분석 템플릿
# ══════════════════════════════════════════════════════════════════════════════

ANALYSIS_TEMPLATE = """\
# AI/Semiconductor Daily News
## Automotive/Humanoid and Storage Intelligence

수집된 뉴스 기사들을 분석하여 반도체 기획자용 전략 의사결정 보고서를 작성하세요.
반드시 10개 섹션(## 1. ~ ## 10.)과 마지막 섹션 ## 12.를 포함해야 합니다.

## 1. 핵심 요약
오늘 가장 중요한 뉴스 3가지를 각각 1-2줄로 요약하세요.
- 각 항목 끝에 반드시 출처 URL 표기: [출처: URL]
- 기술적 관점과 비즈니스 관점을 모두 포함
- 데이터 이동 효율 또는 메모리 병목과 관련된 시사점 우선 선정

## 2. 기술적 의미 분석
기존 기술(Legacy) 대비 변화점을 분석하세요.
- 기술적 진보 수준: 점진적 개선 vs 패러다임 전환 여부 판단
- 핵심 변화 포인트: 아키텍처, 인터페이스(PCIe Gen6/CXL), 전력, 성능
- 데이터 이동 경로 변화 및 대역폭 영향
- SoC/AP 아키텍처 변화가 Storage 인터페이스(UFS 4.0/5.0, NVMe PCIe Gen6) 요구 사양에 미치는 영향
- 실현 가능성 및 양산 시점 예측

## 3. AI Agent 아키텍처 영향
On-device AI와 Cloud AI 구조 변화를 추적하세요.
- On-device 처리 vs Cloud 오프로드 비율 변화를 **반드시 아래 형식으로 3개 시점 포함**:
  2024년: On-device XX% : Cloud XX%
  2026년: On-device XX% : Cloud XX%  (현재 추정)
  2028년: On-device XX% : Cloud XX%  (전망)
- KV Cache 요구량 변화: 컨텍스트 길이 증가가 스토리지에 미치는 영향
  (예: 컨텍스트 2배 → KV Cache 스토리지 요구량 X배 증가 추정)
- Agentic AI / Physical AI 관점의 아키텍처 시사점
- Edge 추론 vs 클라우드 오프로드 결정 기준 변화
- **[AP→DRAM→Storage 연쇄 분석]** 오늘 뉴스에 SoC/AP 발표·변화가 있는 경우에만 작성:
  AP 메모리 인터페이스 결정(LPDDR 세대) → DRAM 대역폭 요구량(GB/s) → 잔여 Storage I/O 버짓 →
  UFS 4.0/5.0 vs NVMe PCIe Gen6 선택 기준 도출 (해당 뉴스 없으면 이 항목 생략)

## 4. 비즈니스 영향
- 관련 기업 시장 점유율 변화 가능성 (기업명 명시)
- 신규 비즈니스 모델(Monetization) 기회
- 단기 수혜 기업 vs 위협받는 기업 구분
- 국내 메모리·스토리지 업체(삼성, SK하이닉스, Kioxia 등) 포지션 변화

## 5. Ecosystem 영향
- OEM(완성차), Tier 1(보쉬/콘티넨탈), SoC 설계사, ODM 간 주도권 변화
- 새로운 협력/경쟁 구도 형성 여부
- 표준화(AUTOSAR, SOAFEE, NVMe, UFS) 및 플랫폼 Lock-in 동향
- Zonal Architecture 전환이 스토리지 아키텍처에 미치는 영향

## 6. 향후 전망
단기/중장기 주요 이벤트를 아래 3열 마크다운 표로 작성하세요 (최소 4행, 데이터 누락 금지):
열 구성: 이벤트 | 예상 시점 | 의미
- 단기(6개월~1년): 제품 출시·계약·인증 일정 등 구체적 이벤트 최소 2건
- 중장기(3~5년): 시장 파급력·기술 성숙도 예측 최소 2건
- 불확실성 요인: 규제(UN-R155, ISO 26262), 공급망, 기술 장벽

## 7. 메모리·스토리지 시장 영향
**[DRAM 파트]**
- HBM(AI 서버), LPDDR5X/6(차량·엣지) 수요 변화 및 대역폭 요구사항 (수치 포함)
- Samsung, SK하이닉스, Micron DRAM 포지션 변화

**[Storage 파트 — 반드시 DRAM과 분리하여 작성]**
- UFS 4.0/5.0, PCIe Gen6 NVMe SSD 차량용 수요 변화
- 용량·랜덤 Read·Write 속도·지연시간 요구사항 변화 (수치 포함)
- Kioxia, Samsung, Micron, SK하이닉스 차량용 NAND/SSD 포지션 변화
- TLC vs QLC 선택 기준 변화 (내구성·비용 트레이드오프)
- NAND vs DRAM 투자 우선순위 변화 시사점

**[AP→DRAM→Storage 연결]**
- 오늘 뉴스 기반으로 SoC 세대 변화가 DRAM 스펙을 바꾸고, 그것이 Storage 선택에 미치는 영향 1-2줄 요약
  (해당 뉴스 없으면 생략)

## 8. 스토리지 Workload 심층 분석
**반드시 수치적 추론을 포함하세요. 모든 수치 항목에 📰/🔢/📊 라벨 필수.**
**🔢 수치 추론 항목은 반드시 [계산 근거: ...] 블록을 다음 줄에 작성하세요.**

**Read/Write Ratio 분석:**
- AI 추론 워크로드(KV Cache Read): 예상 R:W 비율과 그 근거 📰 또는 🔢
  🔢 항목 예시: Read:Write = 10:1 추정
  [계산 근거: Transformer 추론 시 KV Cache 1회 Write → 평균 토큰 생성 10회 Read,
   컨텍스트 4K 기준 / 가정: 배치 크기 1, prefill 1회]
- 센서 데이터 로깅(카메라 8MP×8ea / LiDAR 100만 포인트/초): 연속 Write 속도 추정 🔢
  [계산 근거: 카메라 XX MB/s + LiDAR XX MB/s = 합산 XX MB/s,
   가정: H.265 압축률 20:1 적용 / 원본 대비 압축 후 기록량]
- ADAS 이벤트 로깅(긴급 제동·충돌) vs 정상 주행 로깅 Write 비율 차이 🔢 또는 📊

**WAF (Write Amplification Factor) 영향:**
- 차량 환경(-40°C~+125°C) + Small Random Write 조건에서 WAF 추정 🔢
  [계산 근거: 일반 소비자 SSD WAF 기준값 X.X에서
   온도 범위 확장으로 인한 erase cycle 증가 계수 Y → WAF = X.X × Y = Z.Z 추정,
   가정: 4KB Random Write 비율 AA%, 블록 크기 BB MB]
- WAF 상승이 TBW 수명에 미치는 영향 🔢
  [계산 근거: 제품 보증 TBW = N TB / WAF Z.Z → 실효 TBW = N/Z.Z TB
   → 차량 수명 10년 기준 연간 허용 Write = (N/Z.Z)/10 TB/년]
- 오늘 뉴스 기준 차량용 NAND 선정 기준 변화 (TLC vs QLC P/E cycle 비교) 📰 또는 📊

**Capacity Planning:**
- 현재 ADAS 아키텍처 vs End-to-End AI(FSD v12급) 전환 시 로컬 스토리지 요구량 🔢 또는 📰
  [계산 근거: E2E 모델 파라미터 크기 × 정밀도(FP16/INT8) = 모델 적재 용량
   + KV Cache 요구량(컨텍스트 길이 × 레이어 수 × 헤드 크기) + OS/로그 여유분]
- FSD v12급 기준 차량 탑재 스토리지 최소 용량 도출 📊 또는 🔢
- Sequential vs Random I/O 비율 및 UFS 4.0/5.0 vs NVMe PCIe Gen5/6 선택 근거 🔢

## 9. 지역별 동향 분석
- **미국**: 설계·IP 관점 (NVIDIA, Qualcomm, Mobileye, 인텔 파운드리)
- **중국**: 공급망·자체개발 (화웨이, BYD, CXMT, YMTC의 차량용 NAND)
- **한국**: 메모리·스토리지 (삼성, SK하이닉스의 UFS/SSD 차량 인증 현황)
- **유럽**: 규제·안전 (UN-R155, ISO 26262, Functional Safety 요구사항)
- **일본**: Kioxia, Renesas 등 소재·부품 관점

## 10. Why Now? — 전략적 시급성
왜 지금 이 뉴스가 중요한지 평가하세요.
- 타이밍의 의미: 시장 사이클, 경쟁 압력, 규제 마감
- Signal vs Noise 구분: 지금 당장 주목해야 할 신호
- 분석가 관점 핵심 액션 아이템 2-3개 (구체적 기업/기술/시장 제시)
- 다음 모니터링 포인트 (날짜/이벤트 기준)

{memory_section}
## 12. 전략 권고사항 — 반도체 기획자 액션 아이템
위 분석 전체를 종합하여 반도체 기획자가 취해야 할 구체적 행동을 제시하세요.

**[즉시 행동 (1개월 내)]** 구체적 액션 2-3개 (기업명·기술명·수치 포함)

**[중기 모니터링 (3-6개월)]**
- 자동차 OEM/Tier1 SoC 채택 변화 추적 대상 및 시그널
- 휴머노이드 로봇 업체 SoC 채택 변화 추적 대상 및 시그널
- 기타 주시해야 할 협력관계·전략 변화

**[리스크 경보]** 간과하면 안 되는 위협 요소 1-2개
- 자동차/휴머노이드 시장에서 중국 업체·SoC의 급부상 여부 포함

---
[AI 기여 모델]
{model_attribution}

분석 대상 뉴스 ({count}건):
{articles_text}
"""

WEEKLY_TEMPLATE = """\
지난 한 주간 일별 보고서를 종합하여 반도체 기획자용 Weekly 전략 보고서를 작성하세요.

## 1. 이번 주 핵심 테마 (Top 3)
## 2. 기술 트렌드 주간 요약 (데이터 이동 효율/메모리 병목 관점)
## 3. AI Agent/Physical AI 아키텍처 주간 동향
## 4. 메모리·스토리지 시장 주간 신호 (WAF/TBW/KV Cache 관점)
## 5. SDV/자율주행 주간 흐름 (Zonal Architecture 포함)
## 6. 휴머노이드·로봇 주간 동향
## 7. Ecosystem 주도권 변화 (OEM/Tier1/SoC/ODM)
## 8. 지역별 주간 동향 (미국/중국/한국/유럽/일본)
## 9. 다음 주 Watch List (3개 이내 — 모니터링 기업·기술·이벤트)
## 10. 주간 전략 결론 및 권고사항 (액션 아이템 포함)

---
[AI 기여 모델]
{model_attribution}

일별 보고서 ({count}개):
{combined}
"""


# ══════════════════════════════════════════════════════════════════════════════
# 내부 유틸
# ══════════════════════════════════════════════════════════════════════════════

def _format_articles(articles: list[Article]) -> str:
    """
    기사 목록을 LLM 프롬프트용 텍스트로 변환.
    - full_text + summary 결합: Gemini 배경 조사 내용도 반드시 포함
    - Groq 점수/이유 포함: 합성 LLM에 중요도 전달
    - 기사 수에 따라 본문 길이 자동 조절 (전체 토큰 예산 준수)
    """
    # 기사 수에 따라 기사당 본문 자동 조절
    n = max(len(articles), 1)
    per_article_budget = min(MAX_ARTICLE_BODY_CHARS,
                             MAX_TOTAL_ARTICLE_CHARS // n)

    parts = []
    total_chars = 0

    for i, a in enumerate(articles, 1):
        pub = a.published.strftime("%Y-%m-%d %H:%M UTC") if a.published else "날짜 미상"

        # ── Groq 중요도 점수 표기 ────────────────────────────
        score_line = (
            f"[중요도: {a.groq_score}/10 | Groq 평가: {a.groq_reason}]\n"
            if a.groq_score > 0 else ""
        )

        # ── 본문 + Gemini 배경 조사 결합 ──────────────────────
        body_segments = []
        if a.full_text:
            body_segments.append(a.full_text[:per_article_budget])
        if a.summary:
            if a.summary[:100] not in (a.full_text or ""):
                body_segments.append(f"[요약/배경]\n{a.summary[:500]}")
        body = "\n\n".join(body_segments) if body_segments else "(본문 없음)"
        body = body[:per_article_budget]

        block = (
            f"[{i}] {a.source} | {pub}\n"
            f"{score_line}"
            f"제목: {a.title}\n"
            f"URL: {a.url}\n"
            f"키워드: {', '.join(a.matched_keywords)}\n"
            f"내용:\n{body}\n"
        )
        total_chars += len(block)

        # 전체 예산 초과 시 중단
        if total_chars > MAX_TOTAL_ARTICLE_CHARS:
            logger.info("전체 기사 텍스트 예산 초과 → %d건에서 중단 (총 %d자)",
                        i - 1, total_chars)
            break

        parts.append(block)

    return "\n---\n".join(parts)


def _build_source_items(articles: list[Article]) -> list[dict]:
    """
    출처 표시용 아이템 목록 생성.
    - URL 중복 제거
    - Groq 점수 내림차순 정렬
    - 각 항목: {title, url, source, summary}
    """
    seen_urls: set[str] = set()
    items: list[dict] = []
    for a in sorted(articles, key=lambda x: x.groq_score, reverse=True):
        if not a.url or a.url in seen_urls:
            continue
        seen_urls.add(a.url)
        items.append({
            "title":   a.title or "",
            "url":     a.url,
            "source":  a.source or "",
            "summary": (a.summary or "")[:150],
        })
    return items[:20]


def _parse_sections(text: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    matches = list(re.finditer(r"^##\s+(.+)$", text, re.MULTILINE))
    for i, m in enumerate(matches):
        title = m.group(1).strip()
        start = m.end()
        end   = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections[title] = text[start:end].strip()
    return sections


def _build_model_attribution(filter_meta: dict, research_meta: dict,
                              synthesis_provider: str) -> str:
    """AI 기여 모델 표기 문자열 생성."""
    parts = [f"합성/인사이트: {synthesis_provider}"]

    if filter_meta.get("used_groq"):
        groq_model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
        parts.append(f"고속 필터링: Groq ({groq_model})")

    if research_meta.get("used_gemini"):
        parts.append(f"사실 조사: Gemini ({research_meta.get('model', 'gemini-2.0-flash')})")

    return " | ".join(parts)


# ══════════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════════

import os

# ── 합성 LLM 입력 제한 ────────────────────────────────────────────────────────
MAX_ARTICLES_FOR_SYNTHESIS = 25   # Groq 한도 대응: 상위 25건만 합성에 사용
MAX_ARTICLE_BODY_CHARS     = 2000 # 기사당 본문 최대 (기사 수 많을 때 자동 축소)
MAX_TOTAL_ARTICLE_CHARS    = 40_000  # 전체 기사 텍스트 상한 (~10k 토큰)


def analyze_articles(
    articles: list[Article],
    date_str: str | None = None,
    status_fn=None,
    filter_meta: dict | None = None,
    research_meta: dict | None = None,
    memory_context: str | None = None,
    spike_report: str | None = None,
) -> dict:
    """
    앙상블 분석 파이프라인.
    Groq 필터링·Gemini 조사 메타데이터를 받아 AI 기여 모델을 표기합니다.
    memory_context: Qdrant에서 검색한 과거 인사이트 (없으면 None).
    """
    if not articles:
        logger.warning("분석할 기사가 없습니다.")
        return {"error": "수집된 기사 없음", "raw": "", "date": date_str or ""}

    filter_meta   = filter_meta   or {}
    research_meta = research_meta or {}
    date_str      = date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # ── 합성용 기사 선별: Groq 점수 내림차순 → 상위 MAX_ARTICLES_FOR_SYNTHESIS건 ──
    synthesis_articles = sorted(articles, key=lambda a: a.groq_score, reverse=True)
    synthesis_articles = synthesis_articles[:MAX_ARTICLES_FOR_SYNTHESIS]
    if len(articles) > len(synthesis_articles):
        logger.info("합성 입력 기사 수 제한: %d건 → %d건 (Groq 점수 상위)",
                    len(articles), len(synthesis_articles))

    articles_text = _format_articles(synthesis_articles)

    # 분석 시작 전 임시 attribution (합성 provider는 call_llm 후 결정됨)
    attribution_placeholder = (
        "합성/인사이트: [분석 중...] | "
        + ("고속 필터링: Groq | " if filter_meta.get("used_groq") else "")
        + ("사실 조사: Gemini" if research_meta.get("used_gemini") else "")
    ).rstrip(" |")

    memory_section = ""
    if memory_context or spike_report:
        memory_section = "## 11. 과거 대비 변화 감지 🔍\n"
        if spike_report:
            memory_section += spike_report + "\n"
        if memory_context:
            memory_section += """\
위에 제공된 [📚 과거 관련 인사이트]를 바탕으로 아래 항목을 분석하세요.
과거 인사이트가 충분하지 않은 항목은 생략하세요.

**[자동차 OEM/Tier1]**
- OEM·Tier1(보쉬·콘티넨탈·덴소 등) 간 협력관계 신규 체결 또는 해소 감지
- 자동차 SoC 채택 변화: 과거 사용 칩 → 현재 변경 칩 명시 (예: NVIDIA Thor → Qualcomm SA8295) ⚠️
- OEM/Tier1 전략 변화 심층 비교 (SDV·자율주행·전동화 방향성 변화)

**[휴머노이드 로봇]**
- 신규 업체 등장 또는 기존 업체 전략·자금 변화 모니터링
- 기술·아키텍처 변화: 구동 방식(전동/유압), 센서 구성, 소프트웨어 스택
- 휴머노이드 SoC 채택 변화: 과거 → 현재 변경 칩 명시 (예: NVIDIA Orin → Thor) ⚠️

**[공통]**
- 트렌드 연속성: 지속되는 흐름
- 이상 감지: 예상과 다른 급격한 변화 ⚠️
- 신규 등장: 최근 처음 부각된 기업·기술·이슈

"""

    formatted_template = ANALYSIS_TEMPLATE.format(
        count=len(synthesis_articles),
        articles_text=articles_text,
        model_attribution=attribution_placeholder,
        memory_section=memory_section,
    )
    user_content = (
        memory_context + "\n" + formatted_template
        if memory_context else formatted_template
    )

    logger.info("LLM 앙상블 분석 시작 (기사: %d건 / 전체 수집: %d건)",
                len(synthesis_articles), len(articles))
    raw_text, provider = call_llm(SYSTEM_PROMPT, user_content, status_fn=status_fn)
    logger.info("분석 완료 (provider: %s)", provider)

    # 최종 attribution 삽입
    final_attribution = _build_model_attribution(filter_meta, research_meta, provider)
    raw_text = raw_text.replace(attribution_placeholder, final_attribution)

    # ── 섹터별 기사 수 (Executive Overview 용) ──────────────────────────────
    _AI_INFRA_CATS = {
        "semiconductor", "ai", "memory", "storage", "crossref",
        "company_news", "earnings", "patent", "research", "conference", "korea",
    }
    _SDV_CATS      = {"sdv", "automotive"}
    _HUMANOID_CATS = {"humanoid"}
    sector_counts = {
        "AI Infra": sum(1 for a in articles if getattr(a, "category", "") in _AI_INFRA_CATS),
        "SDV":      sum(1 for a in articles if getattr(a, "category", "") in _SDV_CATS),
        "Humanoid": sum(1 for a in articles if getattr(a, "category", "") in _HUMANOID_CATS),
    }

    return {
        "date": date_str,
        "article_count": len(articles),           # 전체 수집 건수
        "synthesis_count": len(synthesis_articles),  # 실제 분석 건수
        "provider": provider,
        "model_attribution": final_attribution,
        "filter_meta": filter_meta,
        "research_meta": research_meta,
        "raw": raw_text,
        "sections": _parse_sections(raw_text),
        "sources": list({a.source for a in articles}),
        "source_urls": list({a.url for a in articles if a.url}),
        # 출처 표시용 title+url 쌍 (중복 URL 제거, Groq 점수 높은 순)
        "source_items": _build_source_items(articles),
        "keywords_found": list({kw for a in articles for kw in a.matched_keywords}),
        "sector_counts": sector_counts,
    }


def analyze_weekly(daily_analyses: list[dict]) -> dict:
    """Weekly 보고서 생성."""
    combined = "\n\n===\n\n".join(
        f"[{d.get('date', 'N/A')}] (provider: {d.get('provider', '-')})\n{d.get('raw', '')}"
        for d in daily_analyses
    )

    # Weekly attribution
    attribution = "합성/인사이트: Claude (Weekly 종합) | 데이터 출처: Daily 보고서"
    user_content = WEEKLY_TEMPLATE.format(
        count=len(daily_analyses),
        combined=combined[:15000],
        model_attribution=attribution,
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
        "model_attribution": f"합성: {provider} | 데이터: Daily 보고서 {len(daily_analyses)}개",
    }
