"""火山方舟 ARK（豆包）客户端 —— OpenAI 兼容 /chat/completions。

只依赖 requests。关键职责：
  - 统一的 chat() 调用，带重试与超时；
  - **欠费显式告警**：识别 403 AccountOverdueError 并抛出 AccountOverdueError，
    绝不静默降级（历史事故根因）；
  - chat_json()：要求模型返回 JSON 并稳健解析（容忍 ```json 包裹）。
"""
from __future__ import annotations

import json
import re
import time
from typing import Any

import requests

import config
from logging_utils import AccountOverdueError, alert_overdue, get_logger

log = get_logger("doubao")

# 命中即判定为欠费的特征串（大小写不敏感）
_OVERDUE_MARKERS = (
    "accountoverdue",
    "account overdue",
    "insufficient balance",
    "arrears",
    "欠费",
    "余额不足",
)


def _looks_overdue(status_code: int, body: str) -> bool:
    low = (body or "").lower()
    if any(m in low for m in _OVERDUE_MARKERS):
        return True
    # 部分情况下欠费只返回 403 且 message 含 overdue
    return status_code == 403 and "overdue" in low


class DoubaoClient:
    def __init__(
        self,
        api_key: str | None = None,
        endpoint: str | None = None,
        max_retries: int = 3,
        timeout: int = 120,
    ) -> None:
        self.api_key = api_key or config.VOLC_API_KEY
        self.endpoint = (endpoint or config.VOLC_ENDPOINT).rstrip("/")
        self.max_retries = max_retries
        self.timeout = timeout
        if not self.api_key:
            raise ValueError("VOLC_API_KEY 未配置，无法调用豆包。")
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
        )

    # ---- 底层调用 --------------------------------------------------------
    def chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float = 0.3,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> str:
        """返回 assistant 文本内容。欠费抛 AccountOverdueError；其余失败重试后抛异常。"""
        url = f"{self.endpoint}/chat/completions"
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens
        payload.update(kwargs)

        last_err: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self._session.post(url, json=payload, timeout=self.timeout)
            except requests.RequestException as exc:
                last_err = exc
                wait = 2 ** attempt
                log.warning("ARK 网络异常(%d/%d): %s，%ds 后重试", attempt, self.max_retries, exc, wait)
                time.sleep(wait)
                continue

            if resp.status_code == 200:
                data = resp.json()
                try:
                    return data["choices"][0]["message"]["content"]
                except (KeyError, IndexError) as exc:
                    raise RuntimeError(f"ARK 返回结构异常: {data}") from exc

            body = resp.text
            # ---- 欠费：致命，立即告警并抛出，不再重试 ----
            if _looks_overdue(resp.status_code, body):
                alert_overdue(log, detail=body[:300])
                raise AccountOverdueError(body[:500])

            # ---- 限流 / 5xx：退避重试 ----
            if resp.status_code == 429 or resp.status_code >= 500:
                last_err = RuntimeError(f"HTTP {resp.status_code}: {body[:200]}")
                wait = 2 ** attempt
                log.warning("ARK %s(%d/%d)，%ds 后重试", resp.status_code, attempt, self.max_retries, wait)
                time.sleep(wait)
                continue

            # ---- 其它 4xx：不重试 ----
            raise RuntimeError(f"ARK 调用失败 HTTP {resp.status_code}: {body[:300]}")

        raise RuntimeError(f"ARK 重试 {self.max_retries} 次仍失败: {last_err}")

    # ---- JSON 便捷封装 ---------------------------------------------------
    def chat_json(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float = 0.2,
        **kwargs: Any,
    ) -> Any:
        """要求模型返回 JSON 并解析。解析失败返回 None（调用方决定如何容错）。"""
        content = self.chat(messages, model=model, temperature=temperature, **kwargs)
        return _extract_json(content)


def _extract_json(text: str) -> Any:
    """从模型输出里稳健地提取 JSON，容忍 ```json 代码块与前后噪声。"""
    if not text:
        return None
    # 去掉 ```json ... ``` 包裹
    fenced = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    candidate = fenced.group(1).strip() if fenced else text.strip()
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    # 退而求其次：截取第一个 { 或 [ 到最后一个 } 或 ]
    for open_ch, close_ch in (("[", "]"), ("{", "}")):
        start = candidate.find(open_ch)
        end = candidate.rfind(close_ch)
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(candidate[start : end + 1])
            except json.JSONDecodeError:
                continue
    log.warning("无法解析模型 JSON 输出，前 200 字符: %s", candidate[:200])
    return None
