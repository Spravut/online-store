"""Отправка уведомлений в Telegram.

Токен бота и chat_id никогда не хранятся в коде — только в переменных окружения
(`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`) либо в файле `.env`, который добавлен
в `.gitignore`. Если они не заданы, отправка тихо пропускается, а сообщение
пишется в лог — это позволяет запускать job в окружении без алертинга.
"""

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)

API_URL = "https://api.telegram.org/bot{token}/sendMessage"
TIMEOUT_SECONDS = 10


class TelegramNotifier:
    """Минимальный клиент Telegram Bot API: умеет только слать текст."""

    def __init__(
        self,
        token: Optional[str] = None,
        chat_id: Optional[str] = None,
        enabled: Optional[bool] = None,
    ) -> None:
        self.token = token if token is not None else settings.telegram_bot_token
        self.chat_id = chat_id if chat_id is not None else settings.telegram_chat_id
        self.enabled = enabled if enabled is not None else settings.alerts_enabled

    @property
    def configured(self) -> bool:
        return bool(self.token and self.chat_id)

    def send(self, text: str) -> bool:
        """Отправляет сообщение. Возвращает True, если Telegram принял его.

        Никогда не бросает исключение наружу: падение алертинга не должно
        ронять job, который его вызвал.
        """
        if not self.enabled:
            logger.info("алерты отключены (ALERTS_ENABLED=false), сообщение:\n%s", text)
            return False

        if not self.configured:
            logger.warning(
                "TELEGRAM_BOT_TOKEN или TELEGRAM_CHAT_ID не заданы — "
                "сообщение не отправлено:\n%s",
                text,
            )
            return False

        payload = urllib.parse.urlencode(
            {"chat_id": self.chat_id, "text": text, "disable_web_page_preview": "true"}
        ).encode()

        request = urllib.request.Request(
            API_URL.format(token=self.token),
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                body = json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            # Тело ответа Telegram объясняет причину (например, chat not found).
            detail = exc.read().decode(errors="replace")
            logger.error("Telegram вернул HTTP %s: %s", exc.code, detail)
            return False
        except Exception as exc:  # noqa: BLE001 — сеть может упасть как угодно
            logger.error("не удалось отправить уведомление: %s", exc)
            return False

        if not body.get("ok"):
            logger.error("Telegram отклонил сообщение: %s", body)
            return False

        logger.info("уведомление отправлено в Telegram")
        return True
