"""
Gemini 기반 사실 검증 및 배경 조사.
무료 티어 Rate Limit(15 RPM)을 준수하는 지능형 속도 조절.
Gemini 2.0 Flash를 사용하며, 실패 시 건너뜀 (시스템 중단 없음).
"""
import logging
import os
import time
from typing import Optional

logger = logging.getLogger(__name__)

# 무료 티어: 15 RPM → 4초 간격 (안전 마진 포함)
_GEMINI_INTERVAL_SEC = 4.0
# 기사당 조사 배치 크기
_BATCH_SIZE = 3
# 최대 조사 기사 수 (무료 할당량 보존)
_MAX_ARTICLES_TO_RESEARCH = 15

RESEARCH_SYSTEM = """당신은 Automotive/AI 반도체 분야 전문 리서처입니다.
주어진 뉴스 기사의 사실 관계를 검토하고, 기술적 배경과 산업적 맥락을 2-3문장으로 보강하세요.
- 기술 용어(WAF, TBW, KV Cache, PCIe Gen6 등)의 정확한 의미와 맥락 설명
- 관련 기업(Kioxia, Micron, SK하이닉스 등)의 시장 포지션 보완
- 과장·오류 의심 내용은 [검토 필요] 표기
- 한국어로 작성하세요"""


def _has_gemini_key() -> bool:
    val = os.environ.get("GEMINI_API_KEY", "").strip()
    return bool(val) and val not in ("", "your_key_here")


def _call_gemini_with_throttle(model, prompt: str, last_call_time: list) -> Optional[str]:
    """Rate limit 준수 Gemini 호출."""
    import google.generativeai as genai

    # 마지막 호출 이후 충분한 시간이 지났는지 확인
    elapsed = time.time() - last_call_time[0]
    if elapsed < _GEMINI_INTERVAL_SEC:
        wait = _GEMINI_INTERVAL_SEC - elapsed
        logger.debug("[GeminiResearch] Rate limit 대기: %.1f초", wait)
        time.sleep(wait)

    try:
        resp = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(max_output_tokens=512),
        )
        last_call_time[0] = time.time()
        return resp.text
    except Exception as e:
        last_call_time[0] = time.time()
        msg = str(e).lower()
        if "429" in msg or "quota" in msg or "rate" in msg:
            logger.warning("[GeminiResearch] Rate limit 도달 → 해당 배치 건너뜀: %s", e)
            # 추가 백오프
            time.sleep(30)
        else:
            logger.warning("[GeminiResearch] 오류 (건너뜀): %s", e)
        return None


def research_articles(articles: list, max_articles: int = _MAX_ARTICLES_TO_RESEARCH) -> tuple[list, dict]:
    """
    Gemini로 상위 기사들의 배경 조사 및 사실 검증.

    Args:
        articles: Article 객체 리스트 (Groq 필터 후 정렬된 상태)
        max_articles: 최대 조사 기사 수

    Returns:
        (enriched_articles, metadata)
    """
    meta = {
        "used_gemini": False,
        "researched_count": 0,
        "skipped_count": 0,
        "model": "",
    }

    if not articles:
        return articles, meta

    if not _has_gemini_key():
        logger.info("[GeminiResearch] API 키 없음 → 배경 조사 건너뜀")
        return articles, meta

    try:
        import google.generativeai as genai
        genai.configure(api_key=os.environ["GEMINI_API_KEY"])

        model_name = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
        model = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=RESEARCH_SYSTEM,
        )
        meta["model"] = model_name
        meta["used_gemini"] = True

        # 조사 대상: 상위 max_articles건
        to_research = articles[:max_articles]
        last_call_time = [time.time() - _GEMINI_INTERVAL_SEC]  # 첫 호출 즉시 허용

        logger.info("[GeminiResearch] %d건 배경 조사 시작 (model: %s)",
                    len(to_research), model_name)

        # 배치 처리
        for i in range(0, len(to_research), _BATCH_SIZE):
            batch = to_research[i:i + _BATCH_SIZE]
            articles_text = "\n\n".join(
                f"[{j+1}] 제목: {a.title}\n"
                f"출처: {a.source} | URL: {a.url}\n"
                f"내용: {(a.summary or '')[:400]}"
                for j, a in enumerate(batch)
            )

            prompt = (
                f"다음 {len(batch)}건의 뉴스에 대해 각각 기술적 배경 2-3문장을 추가하세요.\n"
                f"형식: [1] 배경 설명\\n[2] 배경 설명\\n...\n\n"
                f"{articles_text}"
            )

            result = _call_gemini_with_throttle(model, prompt, last_call_time)

            if result:
                # 각 기사에 배경 정보 추가
                enrichments = _parse_enrichments(result, len(batch))
                for j, a in enumerate(batch):
                    if j < len(enrichments) and enrichments[j]:
                        # Article 객체에 배경 정보를 summary에 append
                        existing = a.summary or ""
                        a.summary = (existing + "\n\n[Gemini 조사] " + enrichments[j])[:2000]
                        meta["researched_count"] += 1
                    else:
                        meta["skipped_count"] += 1
            else:
                meta["skipped_count"] += len(batch)
                logger.info("[GeminiResearch] 배치 %d-%d 건너뜀", i+1, i+len(batch))

        logger.info("[GeminiResearch] 완료: 조사 %d건 / 건너뜀 %d건",
                    meta["researched_count"], meta["skipped_count"])

        return articles, meta

    except Exception as e:
        logger.warning("[GeminiResearch] 초기화 실패 → 건너뜀: %s", e)
        return articles, meta


def _parse_enrichments(text: str, expected_count: int) -> list[str]:
    """
    Gemini 응답에서 [1], [2], [3] 형태의 배경 설명 추출.
    """
    import re
    results = []
    # [숫자] 로 시작하는 섹션 파싱
    pattern = re.compile(r"\[(\d+)\]\s*(.*?)(?=\[\d+\]|$)", re.DOTALL)
    matches = pattern.findall(text)

    enrichment_map = {}
    for num_str, content in matches:
        num = int(num_str) - 1  # 0-indexed
        enrichment_map[num] = content.strip()

    for i in range(expected_count):
        results.append(enrichment_map.get(i, ""))

    return results
