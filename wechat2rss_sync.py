"""微信公众号源：从 Wechat2RSS 部署自动同步 feed 列表。

Wechat2RSS（https://wechat2rss.xlab.app 等自建部署）把公众号转成 RSS。
它通常暴露一个 OPML / 列表接口。这里做尽力而为的同步：
  - 若配置了 WECHAT2RSS_BASE_URL，则尝试拉取其 feed 列表并转成标准 feed 记录；
  - 拉取成功时打印「自动同步成功,共 N 个公众号」（与交接文档要求一致）；
  - 拉取失败或未配置，则回落到 data/wechat_accounts.json 中已填 feed_id 的条目。

不同 Wechat2RSS 版本接口不完全一致，这里覆盖常见的 OPML 与 JSON 两种；
无法识别时安全跳过，不阻断主流水线。
"""
from __future__ import annotations

import json
import re
from xml.etree import ElementTree as ET

import requests

import config
from logging_utils import get_logger

log = get_logger("wechat2rss")


def _load_local_accounts() -> list[dict]:
    if not config.WECHAT_ACCOUNTS_PATH.exists():
        return []
    data = json.loads(config.WECHAT_ACCOUNTS_PATH.read_text(encoding="utf-8"))
    feeds = []
    base = config.WECHAT2RSS_BASE_URL.rstrip("/") if config.WECHAT2RSS_BASE_URL else ""
    for acc in data.get("accounts", []):
        feed_id = (acc.get("feed_id") or "").strip()
        if not feed_id:
            continue
        # 允许 feed_id 直接是完整 URL，或相对 Wechat2RSS 的 feed 路径
        if feed_id.startswith("http"):
            url = feed_id
        elif base:
            url = f"{base}/feed/{feed_id}.xml"
        else:
            continue
        feeds.append({"name": f"[公众号] {acc.get('name', feed_id)}", "url": url, "tags": ["wechat", "cn"]})
    return feeds


def _try_opml(base: str, token: str) -> list[dict]:
    """尝试 Wechat2RSS 的 OPML 订阅导出。"""
    candidates = [f"{base}/opml", f"{base}/feed/opml", f"{base}/rss/opml.xml"]
    params = {"token": token} if token else {}
    for url in candidates:
        try:
            resp = requests.get(url, params=params, timeout=config.FETCH_TIMEOUT)
        except requests.RequestException:
            continue
        if resp.status_code != 200 or "<opml" not in resp.text.lower():
            continue
        try:
            root = ET.fromstring(resp.text)
        except ET.ParseError:
            continue
        feeds = []
        for outline in root.iter("outline"):
            xml_url = outline.get("xmlUrl")
            title = outline.get("title") or outline.get("text") or "公众号"
            if xml_url:
                feeds.append({"name": f"[公众号] {title}", "url": xml_url, "tags": ["wechat", "cn"]})
        if feeds:
            return feeds
    return []


def _try_json(base: str, token: str) -> list[dict]:
    """尝试 Wechat2RSS 的 JSON 列表接口。"""
    candidates = [f"{base}/api/feeds", f"{base}/feeds.json", f"{base}/list"]
    params = {"token": token} if token else {}
    for url in candidates:
        try:
            resp = requests.get(url, params=params, timeout=config.FETCH_TIMEOUT)
            if resp.status_code != 200:
                continue
            data = resp.json()
        except (requests.RequestException, ValueError):
            continue
        items = data if isinstance(data, list) else data.get("feeds") or data.get("data") or []
        feeds = []
        for it in items:
            if not isinstance(it, dict):
                continue
            url_ = it.get("url") or it.get("xmlUrl") or it.get("feed")
            name = it.get("name") or it.get("title") or "公众号"
            if url_:
                feeds.append({"name": f"[公众号] {name}", "url": url_, "tags": ["wechat", "cn"]})
        if feeds:
            return feeds
    return []


def sync_wechat_feeds() -> list[dict]:
    """返回微信公众号 feed 列表（尽力自动同步，失败回落本地）。"""
    base = config.WECHAT2RSS_BASE_URL.rstrip("/") if config.WECHAT2RSS_BASE_URL else ""
    token = config.WECHAT2RSS_TOKEN

    if base:
        feeds = _try_opml(base, token) or _try_json(base, token)
        if feeds:
            log.info("自动同步成功,共 %d 个公众号", len(feeds))
            return feeds
        log.warning("Wechat2RSS 已配置但未能自动同步（接口不匹配或无权限），回落本地清单。")
    else:
        log.info("未配置 WECHAT2RSS_BASE_URL，使用本地 wechat_accounts.json 中已填 feed_id 的条目。")

    local = _load_local_accounts()
    if local:
        log.info("自动同步成功,共 %d 个公众号（本地清单）", len(local))
    else:
        log.info("暂无可用微信公众号源（本地清单未填 feed_id）。")
    return local


if __name__ == "__main__":
    feeds = sync_wechat_feeds()
    print(json.dumps(feeds, ensure_ascii=False, indent=2))
