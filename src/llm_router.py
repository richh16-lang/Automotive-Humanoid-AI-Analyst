"""
Multi-LLM Router: Claude -> Gemini -> GPT 순서로 폴백.
각 LLM이 실패하면 자동으로 다음 LLM을 시도합니다.
"""
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


# ── Claude (Anthropic) ────────────────────────────────────────────────────────

def _call_claude(system: str, user: str, model: Optional[str] = None) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    model = model or os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")

    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=[
            {
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user}],
    )
    usage = response.usage
    logger.info(
        "[Claude] 완료 | 입력: %d토큰 (캐시히트: %d) | 출력: %d토큰",
        usage.input_tokens,
        getattr(usage, "cache_read_input_tokens", 0),
        usage.output_tokens,
    )
    return response.content[0].text


# ── Gemini (Google) ───────────────────────────────────────────────────────────

def _call_gemini(system: str, user: str, model: Optional[str] = None) -> str:
    import google.generativeai as genai

    genai.configure(api_key=os.environ["GEMINI_API_KEY"])
    model_name = model or os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")

    gemini_model = genai.GenerativeModel(
        model_name=model_name,
        system_instruction=system,
    )
    response = gemini_model.generate_content(
        user,
        generation_config=genai.GenerationConfig(max_output_tokens=4096),
    )
    logger.info("[Gemini] 완료 | 모델: %s", model_name)
    return response.text


# ── GPT (OpenAI) ──────────────────────────────────────────────────────────────

def _call_gpt(system: str, user: str, model: Optional[str] = None) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    model_name = model or os.environ.get("OPENAI_MODEL", "gpt-4o")

    response = client.chat.completions.create(
        model=model_name,
        max_tokens=4096,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    usage = response.usage
    logger.info(
        "[GPT] 완료 | 입력: %d토큰 | 출력: %d토큰",
        usage.prompt_tokens,
        usage.completion_tokens,
    )
    return response.choices[0].message.content


# ── 환경변수 키 존재 여부 확인 ─────────────────────────────────────────────────

def _has_key(env_var: str) -> bool:
    val = os.environ.get(env_var, "").strip()
    return bool(val) and val not in ("your_key_here", "")


# ── Public: 폴백 라우터 ───────────────────────────────────────────────────────

PROVIDERS = [
    ("Claude",  "ANTHROPIC_API_KEY", _call_claude),
    ("Gemini",  "GEMINI_API_KEY",    _call_gemini),
    ("GPT",     "OPENAI_API_KEY",    _call_gpt),
]


def call_llm(system: str, user: str) -> tuple[str, str]:
    """
    사용 가능한 LLM을 순서대로 시도하여 첫 번째 성공 결과 반환.
    반환값: (응답 텍스트, 사용된 provider 이름)
    """
    last_error: Optional[Exception] = None

    for name, key_var, fn in PROVIDERS:
        if not _has_key(key_var):
            logger.info("[Router] %s API 키 없음, 건너뜀", name)
            continue
        try:
            logger.info("[Router] %s 시도 중...", name)
            result = fn(system, user)
            logger.info("[Router] %s 성공", name)
            return result, name
        except Exception as e:
            logger.warning("[Router] %s 실패: %s → 다음 LLM 시도", name, e)
            last_error = e

    raise RuntimeError(
        f"모든 LLM 호출 실패. 마지막 오류: {last_error}"
    )
