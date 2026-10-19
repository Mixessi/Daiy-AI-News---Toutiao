"""飞书群机器人推送（自定义机器人 webhook）。

最轻量的日报分发方式：不需要自建应用与文档权限，只要在飞书群里
「设置 → 群机器人 → 添加机器人 → 自定义机器人」拿到 webhook 地址，
配到 FEISHU_WEBHOOK_URL 即可。机器人若开启「签名校验」，同时配 FEISHU_WEBHOOK_SECRET。

以消息卡片（markdown 元素）发送，超长内容会被截断并附上完整日报链接。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time

import requests

import config
from logging_utils import get_logger, gha_warning

log = get_logger("feishu.webhook")

# 飞书卡片请求体上限约 30KB，留足余量
_MAX_CHARS = 8000


def _sign(secret: str, timestamp: int) -> str:
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def _to_card_markdown(markdown: str) -> str:
    """卡片 markdown 不支持 # 标题，转成加粗行。"""
    lines = []
    for line in markdown.splitlines():
        stripped = line.lstrip("#").strip()
        if line.startswith("#") and stripped:
            lines.append(f"**{stripped}**")
        elif line.startswith("> "):
            lines.append(line[2:])
        else:
            lines.append(line)
    return "\n".join(lines).strip()


def push_report(title: str, markdown: str, link: str = "") -> bool:
    """推送日报卡片。未配置返回 False；推送失败告警但不抛出（分发失败不应让日报本身失败）。"""
    if not config.FEISHU_WEBHOOK_URL:
        return False

    body = _to_card_markdown(markdown)
    if len(body) > _MAX_CHARS:
        body = body[:_MAX_CHARS].rsplit("\n", 1)[0] + "\n\n……（内容过长已截断）"
    if link:
        body += f"\n\n[查看完整日报]({link})"

    payload: dict = {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {"template": "blue", "title": {"tag": "plain_text", "content": title}},
            "elements": [{"tag": "markdown", "content": body}],
        },
    }
    if config.FEISHU_WEBHOOK_SECRET:
        ts = int(time.time())
        payload["timestamp"] = str(ts)
        payload["sign"] = _sign(config.FEISHU_WEBHOOK_SECRET, ts)

    try:
        resp = requests.post(config.FEISHU_WEBHOOK_URL, json=payload, timeout=config.FETCH_TIMEOUT)
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        log.warning("飞书群机器人推送失败：%s", exc)
        gha_warning(f"飞书群机器人推送失败：{exc}")
        return False
    if data.get("code", data.get("StatusCode", 0)) != 0:
        log.warning("飞书群机器人推送被拒：%s", data)
        gha_warning(f"飞书群机器人推送被拒：{data}")
        return False
    log.info("已推送日报到飞书群。")
    return True
