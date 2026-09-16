from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any


def _post_json(url: str, payload: dict[str, Any], timeout: int = 30) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
    return json.loads(body) if body else {}


def deliver(digest: str, config: dict[str, Any]) -> str:
    delivery = config.get("delivery") or {}
    channel = delivery.get("channel", "local")
    if channel == "local":
        return "local: digest written to run directory"
    if channel == "feishu":
        webhook = os.getenv("FEISHU_WEBHOOK_URL", "")
        if not webhook:
            raise RuntimeError("delivery.channel=feishu，但 FEISHU_WEBHOOK_URL 未配置")
        response = _post_json(webhook, {"msg_type": "text", "content": {"text": digest}})
        if response.get("code", response.get("StatusCode", 0)) not in (0, None):
            raise RuntimeError(f"飞书投递失败：{response}")
        return "feishu: delivered"
    if channel == "telegram":
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        if not token or not chat_id:
            raise RuntimeError("delivery.channel=telegram，但 TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID 未配置")
        payload = {"chat_id": chat_id, "text": digest, "disable_web_page_preview": True}
        response = _post_json(f"https://api.telegram.org/bot{token}/sendMessage", payload)
        if not response.get("ok"):
            raise RuntimeError(f"Telegram 投递失败：{response}")
        return "telegram: delivered"
    raise ValueError(f"不支持的投递渠道：{channel}")
