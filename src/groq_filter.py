"""
Groq 기반 고속 뉴스 필터링 및 우선순위 결정.
Llama 3.3 70B의 초고속 추론(100+ tok/s)으로 수십 건의 뉴스를
반도체/모빌리티 관련성 기준으로 필터링하고 순위를 매깁니다.
"""
import json
import logging
import os
import time
from typing import Optional

logger = logging.getLogger(__name__)

FILTER_SYSTEM = """You are an expert filter for Automotive/AI semiconductor intelligence.
Score each news article for relevance to: SDV, autonomous driving, AI chips,
memory/storage (UFS/SSD/NAND), humanoid robots, KV cache, PCIe, WAF/TBW.

Scoring:
10: Core semiconductor/automotive AI news (direct product/market/tech impact)
7-9: Closely related AI, mobility, or memory news
4-6: Tangentially related tech news
1-3: Irrelevant (general news, politics, sports, etc.)

Respond ONLY with a JSON array:
[{"id": 0, "score": 8, "reason": "NVIDIA automotive chip announcement"}, ...]"""


def _has_groq_key() -> bool:
    val = os.environ.get("GROQ_API_KEY", "").strip()
    return bool(val) and val not in ("", "your_key_here")


def filter_and_rank(articles: list, top_n: int = 30, min_score: int = 4) -> tuple[list, dict]:
    """
    Groq로 뉴스 필터링 및 우선순위 결정.

    Args:
        articles: Article 객체 리스트
        top_n: 최대 반환 기사 수
        min_score: 최소 관련성 점수 (미만 제거)

    Returns:
        (filtered_articles, metadata)
        metadata = {
            "used_groq": bool,
            "original_count": int,
            "filtered_count": int,
            "scores": list[dict]
        }
    """
    meta = {
        "used_groq": False,
        "original_count": len(articles),
        "filtered_count": len(articles),
        "scores": [],
    }

    if not articles:
        return articles, meta

    if not _has_groq_key():
        logger.info("[GroqFilter] API 키 없음 → 필터링 건너뜀 (전체 %d건 유지)", len(articles))
        return articles[:top_n], meta

    try:
        from groq import Groq
        client = Groq(api_key=os.environ["GROQ_API_KEY"])
        model  = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

        # 배치 준비 (제목 + 요약 200자)
        items = []
        for i, a in enumerate(articles):
            summary = (a.summary or "")[:200].replace("\n", " ")
            items.append({
                "id": i,
                "title": a.title[:150],
                "summary": summary,
                "source": a.source,
            })

        user_prompt = (
            f"Score these {len(items)} articles for automotive/AI semiconductor relevance:\n"
            + json.dumps(items, ensure_ascii=False)
        )

        logger.info("[GroqFilter] %d건 필터링 시작 (model: %s)", len(articles), model)
        t0 = time.time()

        resp = client.chat.completions.create(
            model=model,
            max_tokens=2048,
            temperature=0.1,
            messages=[
                {"role": "system", "content": FILTER_SYSTEM},
                {"role": "user",   "content": user_prompt},
            ],
        )
        elapsed = time.time() - t0
        raw = resp.choices[0].message.content.strip()
        logger.info("[GroqFilter] 완료 (%.1f초) | 입력 %d | 출력 %d 토큰",
                    elapsed, resp.usage.prompt_tokens, resp.usage.completion_tokens)

        # JSON 파싱
        scores = _parse_scores(raw)
        if not scores:
            logger.warning("[GroqFilter] JSON 파싱 실패 → 필터링 건너뜀\n%s", raw[:300])
            return articles[:top_n], meta

        # 점수 맵 구성
        score_map = {s["id"]: s for s in scores}
        meta["scores"] = scores
        meta["used_groq"] = True

        # 필터링 + 정렬
        scored = []
        for i, a in enumerate(articles):
            info = score_map.get(i, {"score": 5, "reason": "no score"})
            scored.append((info["score"], i, a, info.get("reason", "")))

        scored.sort(key=lambda x: x[0], reverse=True)

        filtered = [a for score, _, a, _ in scored if score >= min_score][:top_n]
        meta["filtered_count"] = len(filtered)

        removed = len(articles) - len(filtered)
        logger.info("[GroqFilter] 결과: %d건 → %d건 (제거: %d건, min_score≥%d)",
                    len(articles), len(filtered), removed, min_score)

        # 점수 로그 (상위 10개)
        for score, idx, a, reason in scored[:10]:
            logger.debug("  [%d점] %s — %s", score, a.title[:60], reason[:50])

        return filtered, meta

    except Exception as e:
        logger.warning("[GroqFilter] 오류 발생 → 필터링 건너뜀: %s", e)
        return articles[:top_n], meta


def _parse_scores(raw: str) -> list[dict]:
    """JSON 배열 파싱. 마크다운 코드블록 처리 포함."""
    # ```json ... ``` 제거
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    # JSON 배열 추출
    start = raw.find("[")
    end   = raw.rfind("]")
    if start == -1 or end == -1:
        return []

    try:
        data = json.loads(raw[start:end + 1])
        # 유효성 검사
        return [
            {"id": int(d["id"]), "score": int(d["score"]), "reason": str(d.get("reason", ""))}
            for d in data
            if isinstance(d, dict) and "id" in d and "score" in d
        ]
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        logger.debug("[GroqFilter] JSON 파싱 상세 오류: %s", e)
        return []
