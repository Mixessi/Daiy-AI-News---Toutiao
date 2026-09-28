"""统一抓取所有 RSS/Atom 源并做最近 N 小时窗口过滤。

汇聚三类源：
  - data/rss_feeds.json      科技/AI 媒体
  - data/substack_feeds.json Substack newsletter
  - Wechat2RSS 自动同步的微信公众号

返回归一化的文章 dict 列表：
  { title, url, summary, source, published, published_ts, tags }
"""
from __future__ import annotations

import calendar
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import feedparser
import requests

import config
from logging_utils import get_logger
from wechat2rss_sync import sync_wechat_feeds

log = get_logger("fetch")

# 很多站点（Substack / Cloudflare 后的博客）会对非浏览器 UA 返回 HTML 挑战页，
# feedparser 解析时报 "not well-formed (invalid token)"。用常见浏览器 UA 并声明接受 RSS。
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.5",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def _load_feed_file(path) -> list[dict]:
    if not path.exists():
        log.warning("数据源文件不存在: %s", path)
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [f for f in data.get("feeds", []) if f.get("url")]


def load_all_sources() -> list[dict]:
    sources: list[dict] = []
    sources += _load_feed_file(config.RSS_SOURCES_PATH)
    sources += _load_feed_file(config.SUBSTACK_SOURCES_PATH)
    sources += sync_wechat_feeds()
    log.info("共加载 %d 个数据源（RSS + Substack + 公众号）", len(sources))
    return sources


def _entry_timestamp(entry) -> float | None:
    """从 feed entry 里取发布时间的 unix 秒；取不到返回 None。"""
    for key in ("published_parsed", "updated_parsed"):
        val = entry.get(key)
        if val:
            try:
                return float(calendar.timegm(val))  # feedparser 给的是 UTC struct_time
            except (OverflowError, ValueError, TypeError):
                continue
    return None


def _clean_summary(entry) -> str:
    raw = entry.get("summary") or entry.get("description") or ""
    # 去 HTML 标签，压缩空白
    text = re.sub(r"<[^>]+>", " ", raw)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:600]


def _download(url: str) -> bytes:
    """带超时下载 feed（feedparser 自带的抓取没有超时，单个慢源会卡死整条流水线）。"""
    resp = requests.get(url, headers=_HEADERS, timeout=config.FETCH_TIMEOUT)
    resp.raise_for_status()
    return resp.content


def fetch_one(source: dict, cutoff_ts: float) -> list[dict]:
    url = source["url"]
    name = source.get("name", url)
    try:
        parsed = feedparser.parse(_download(url))
    except Exception as exc:
        log.warning("抓取失败 %s: %s", name, exc)
        return []

    if parsed.bozo and not parsed.entries:
        log.warning("解析异常且无条目 %s: %s", name, getattr(parsed, "bozo_exception", ""))
        return []

    items = []
    for entry in parsed.entries:
        ts = _entry_timestamp(entry)
        # 无发布时间的条目：保守保留（很多 feed 不给时间），但标记 ts=None
        if ts is not None and ts < cutoff_ts:
            continue
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        if not title or not link:
            continue
        items.append(
            {
                "title": title,
                "url": link,
                "summary": _clean_summary(entry),
                "source": name,
                "tags": source.get("tags", []),
                "published_ts": ts,
                "published": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat() if ts else "",
            }
        )

    # 单源上限：防止 arXiv 这类高产源（一天数百篇）淹没其它源、拖慢初筛
    cap = int(source.get("max_items") or config.MAX_ITEMS_PER_SOURCE)
    if len(items) > cap:
        items.sort(key=lambda x: x["published_ts"] or 0, reverse=True)
        log.info("  %s 近窗口内 %d 条，截取最新 %d 条", name, len(items), cap)
        items = items[:cap]
    return items


def fetch_recent(hours: int | None = None) -> list[dict]:
    """抓取所有源，返回最近 `hours` 小时内的去重文章。"""
    hours = hours or config.NEWS_HOURS_LIMIT
    cutoff_ts = time.time() - hours * 3600
    sources = load_all_sources()

    all_items: list[dict] = []
    with ThreadPoolExecutor(max_workers=config.FETCH_WORKERS) as pool:
        futures = {pool.submit(fetch_one, s, cutoff_ts): s for s in sources}
        for fut in as_completed(futures):
            src = futures[fut]
            try:
                items = fut.result()
                if items:
                    log.info("  %-40s → %d 条", src.get("name", "")[:40], len(items))
                all_items.extend(items)
            except Exception as exc:
                log.warning("源处理异常 %s: %s", src.get("name"), exc)

    deduped = _dedupe(all_items)
    log.info("抓取完成：原始 %d 条，去重后 %d 条（近 %dh）", len(all_items), len(deduped), hours)
    return deduped


def _dedupe(items: list[dict]) -> list[dict]:
    """按 URL 去重；无 URL 时按标题。保留最早出现的一条。"""
    seen: set[str] = set()
    out: list[dict] = []
    for it in items:
        key = (it.get("url") or it.get("title", "")).strip().lower().rstrip("/")
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


if __name__ == "__main__":
    got = fetch_recent()
    print(f"\n共 {len(got)} 条：")
    for it in got[:10]:
        print(f" - [{it['source']}] {it['title']}")
