"""
Multi-LLM Router: Claude → Gemini → GPT → Groq → DeepSeek → Mistral 순 폴백.
각 LLM이 실패하면 자동으로 다음 LLM을 시도합니다.
429 Rate Limit은 최대 3회 재시도 후 다음 LLM으로 넘어갑니다.
"""
import logging
import os
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

_RETRY_DELAYS = [10, 30, 60]   # 429 재시도 대기(초)


# ══════════════════════════════════════════════════════════════════════════════
# 각 LLM 호출 함수
# ══════════════════════════════════════════════════════════════════════════════

def _call_claude(system: str, user: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    model  = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
    resp   = client.messages.create(
        model=model, max_tokens=16000,
        system=[{"type": "text", "text": system,
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}],
    )
    u = resp.usage
    logger.info("[Claude] 입력 %d토큰(캐시히트 %d) | 출력 %d토큰",
                u.input_tokens, getattr(u, "cache_read_input_tokens", 0), u.output_tokens)
    return resp.content[0].text


def _call_gemini(system: str, user: str) -> str:
    import google.generativeai as genai
    genai.configure(api_key=os.environ["GEMINI_API_KEY"])
    model_name = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
    model = genai.GenerativeModel(model_name=model_name, system_instruction=system)
    resp  = model.generate_content(
        user,
        generation_config=genai.GenerationConfig(max_output_tokens=16000),
    )
    logger.info("[Gemini] 모델: %s", model_name)
    return resp.text


def _call_gpt(system: str, user: str) -> str:
    from openai import OpenAI
    client     = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    model_name = os.environ.get("OPENAI_MODEL", "gpt-4o")
    resp       = client.chat.completions.create(
        model=model_name, max_tokens=16000,
        messages=[{"role": "system", "content": system},
                  {"role": "user",   "content": user}],
    )
    u = resp.usage
    logger.info("[GPT] 입력 %d토큰 | 출력 %d토큰", u.prompt_tokens, u.completion_tokens)
    return resp.choices[0].message.content


def _call_groq(system: str, user: str) -> str:
    from groq import Groq
    client     = Groq(api_key=os.environ["GROQ_API_KEY"])
    model_name = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
    resp       = client.chat.completions.create(
        model=model_name, max_tokens=8192,
        messages=[{"role": "system", "content": system},
                  {"role": "user",   "content": user}],
    )
    u = resp.usage
    logger.info("[Groq] 모델: %s | 입력 %d | 출력 %d",
                model_name, u.prompt_tokens, u.completion_tokens)
    return resp.choices[0].message.content


def _call_deepseek(system: str, user: str) -> str:
    # DeepSeek은 OpenAI 호환 API를 사용
    from openai import OpenAI
    client     = OpenAI(
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url="https://api.deepseek.com",
    )
    model_name = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
    resp       = client.chat.completions.create(
        model=model_name, max_tokens=16000,
        messages=[{"role": "system", "content": system},
                  {"role": "user",   "content": user}],
    )
    u = resp.usage
    logger.info("[DeepSeek] 모델: %s | 입력 %d | 출력 %d",
                model_name, u.prompt_tokens, u.completion_tokens)
    return resp.choices[0].message.content


def _call_mistral(system: str, user: str) -> str:
    from mistralai import Mistral
    client     = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
    model_name = os.environ.get("MISTRAL_MODEL", "mistral-large-latest")
    resp       = client.chat.complete(
        model=model_name,
        max_tokens=16000,
        messages=[{"role": "system", "content": system},
                  {"role": "user",   "content": user}],
    )
    u = resp.usage
    logger.info("[Mistral] 모델: %s | 입력 %d | 출력 %d",
                model_name, u.prompt_tokens, u.completion_tokens)
    return resp.choices[0].message.content


# ══════════════════════════════════════════════════════════════════════════════
# 폴백 순서 — 품질·가용성 기준
# ══════════════════════════════════════════════════════════════════════════════
#
#  1. Claude    — 최고 품질, 유료
#  2. Gemini    — 우수 품질, 무료 티어 (1,500회/일)
#  3. GPT       — 우수 품질, 유료
#  4. DeepSeek  — 우수 추론력, 사실상 무료 ($0.014/1M 토큰)
#  5. Groq      — 빠른 추론, 무료 (14,400회/일, LLaMA 3.3 70B)
#  6. Mistral   — 양호 품질, 무료 티어

PROVIDERS: list[tuple[str, str, Callable]] = [
    ("Claude",   "ANTHROPIC_API_KEY", _call_claude),
    ("Gemini",   "GEMINI_API_KEY",    _call_gemini),
    ("GPT",      "OPENAI_API_KEY",    _call_gpt),
    ("DeepSeek", "DEEPSEEK_API_KEY",  _call_deepseek),
    ("Groq",     "GROQ_API_KEY",      _call_groq),
    ("Mistral",  "MISTRAL_API_KEY",   _call_mistral),
]


# ══════════════════════════════════════════════════════════════════════════════
# 내부 유틸
# ══════════════════════════════════════════════════════════════════════════════

def _has_key(env_var: str) -> bool:
    val = os.environ.get(env_var, "").strip()
    return bool(val) and val not in ("your_key_here", "")


def _is_rate_limit(e: Exception) -> bool:
    msg = str(e).lower()
    return any(k in msg for k in ("429", "rate limit", "quota",
                                   "resource exhausted", "too many", "rate_limit"))


def _is_too_large(e: Exception) -> bool:
    """413 / 토큰 초과 → 다음 LLM으로 폴백 대상."""
    msg = str(e).lower()
    return any(k in msg for k in ("413", "too large", "tokens per minute",
                                   "request too large", "reduce your message",
                                   "context_length_exceeded", "maximum context"))


# Groq 무료 티어 토큰 한도 (보수적 적용: 8000자 ≈ ~2000토큰 여유 확보)
_GROQ_MAX_USER_CHARS = 18_000


def _call_with_retry(name: str, fn: Callable, system: str, user: str) -> str:
    """
    429 Rate Limit → 최대 3회 재시도 후 다음 LLM으로 폴백.
    413 Too Large  → 즉시 다음 LLM으로 폴백 (재시도 없음).
    기타 에러      → 즉시 다음 LLM으로 폴백.
    """
    # Groq 전용: 프롬프트가 너무 길면 미리 잘라서 413 예방
    if name == "Groq" and len(user) > _GROQ_MAX_USER_CHARS:
        truncated = len(user) - _GROQ_MAX_USER_CHARS
        user = user[:_GROQ_MAX_USER_CHARS] + f"\n\n...[토큰 한도로 {truncated}자 생략]"
        logger.warning("[Router] Groq 입력 %d자 초과 → %d자로 축소",
                       len(user) + truncated, _GROQ_MAX_USER_CHARS)

    last_err: Optional[Exception] = None
    for attempt, delay in enumerate(_RETRY_DELAYS, start=1):
        try:
            return fn(system, user)
        except Exception as e:
            last_err = e
            if _is_rate_limit(e):
                logger.warning("[Router] %s 429 Rate Limit (시도 %d/3) — %d초 후 재시도...",
                               name, attempt, delay)
                time.sleep(delay)
            elif _is_too_large(e):
                logger.warning("[Router] %s 413 Too Large → 다음 LLM으로 폴백", name)
                raise   # 재시도 없이 즉시 폴백
            else:
                raise
    raise last_err  # type: ignore


# ══════════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════════

def call_llm(
    system: str,
    user: str,
    status_fn: Optional[Callable[[str], None]] = None,
) -> tuple[str, str]:
    """
    사용 가능한 LLM을 순서대로 시도하여 첫 번째 성공 결과 반환.
    반환값: (응답 텍스트, 사용된 provider 이름)
    status_fn: 진행 상태를 외부(Streamlit 등)에 전달하는 선택적 콜백
    """
    def _notify(msg: str) -> None:
        logger.info(msg)
        if status_fn:
            try:
                status_fn(msg)
            except Exception:
                pass

    last_error: Optional[Exception] = None
    test_mode  = os.environ.get("TEST_MODE", "").lower() in ("1", "true", "yes")
    skip_paid  = {"Claude", "GPT", "DeepSeek"}  # 테스트 시 유료 LLM 제외

    for name, key_var, fn in PROVIDERS:
        if test_mode and name in skip_paid:
            _notify(f"⬜ {name}: TEST_MODE — 건너뜀")
            continue
        if not _has_key(key_var):
            _notify(f"⬜ {name}: API 키 없음, 건너뜀")
            continue
        try:
            _notify(f"🔄 {name} 분석 시작...")
            result = _call_with_retry(name, fn, system, user)
            _notify(f"✅ {name} 분석 완료")
            return result, name
        except Exception as e:
            _notify(f"❌ {name} 실패: {str(e)[:300]} → 다음 LLM 시도")
            last_error = e

    raise RuntimeError(f"모든 LLM 호출 실패. 마지막 오류: {last_error}")


def get_available_providers() -> list[dict]:
    """현재 API 키가 등록된 provider 목록 반환 (UI 표시용)."""
    result = []
    for name, key_var, _ in PROVIDERS:
        val = os.environ.get(key_var, "").strip()
        if not val:
            status = "none"
        elif name == "Claude"   and not val.startswith("sk-ant-"):
            status = "invalid"
        elif name == "GPT"      and not val.startswith("sk-"):
            status = "invalid"
        elif name == "Gemini"   and not val.startswith("AIza"):
            status = "invalid"
        else:
            status = "ok"
        result.append({"name": name, "key_var": key_var, "status": status})
    return result
