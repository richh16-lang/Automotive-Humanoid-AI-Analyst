"""
텔레그램 급증 감지 알림.
Entity Tracker에서 급증/신규 등장 감지 시에만 발송.
"""
import logging
import os

logger = logging.getLogger(__name__)


def _has_telegram() -> bool:
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
                and os.environ.get("TELEGRAM_CHAT_ID", "").strip())


def send_spike_alert(spike_report: str, spike_entities: list[str],
                     date_str: str, notion_url: str = "") -> bool:
    """
    급증 감지 시 텔레그램 메시지 발송.
    spike_report가 비어있으면 발송 안 함.
    반환값: 발송 성공 여부
    """
    if not spike_report or not spike_entities:
        return False
    if not _has_telegram():
        logger.warning("[Telegram] TELEGRAM_BOT_TOKEN 또는 CHAT_ID 미설정")
        return False

    token   = os.environ["TELEGRAM_BOT_TOKEN"].strip()
    chat_id = os.environ["TELEGRAM_CHAT_ID"].strip()

    notion_line = f"\n🔗 [보고서 보기]({notion_url})" if notion_url else ""

    message = (
        f"🚨 *ARIA 이상감지 알림* | {date_str}\n"
        f"{'─' * 30}\n"
        f"{spike_report.strip()}\n"
        f"{'─' * 30}"
        f"{notion_line}"
    )

    import urllib.request, urllib.parse, json as _json
    url  = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id":    chat_id,
        "text":       message,
        "parse_mode": "Markdown",
    }).encode()

    try:
        req  = urllib.request.Request(url, data=data, method="POST")
        resp = urllib.request.urlopen(req, timeout=10)
        result = _json.loads(resp.read())
        if result.get("ok"):
            logger.info("[Telegram] 알림 발송 완료: %s", ", ".join(spike_entities))
            return True
        else:
            logger.warning("[Telegram] 발송 실패: %s", result)
            return False
    except Exception as e:
        logger.warning("[Telegram] 발송 오류: %s", e)
        return False
