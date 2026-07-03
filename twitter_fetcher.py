"""Twitter/X 抓取（via SocialData，https://socialdata.tools）。

需要 SOCIALDATA_API_KEY，缺则返回空（调用方跳过）。被 twitter_opinions 与
kol_digest 复用。
"""
from __future__ import annotations

import requests

import config
from logging_utils import get_logger

log = get_logger("twitter")

_BASE = "https://api.socialdata.tools"


def available() -> bool:
    return bool(config.SOCIALDATA_API_KEY)


def _headers() -> dict:
    return {"Authorization": f"Bearer {config.SOCIALDATA_API_KEY}", "Accept": "application/json"}


def fetch_user_tweets(handle: str, limit: int = 20) -> list[dict]:
    """抓取某用户最近推文。失败/未配置返回空列表。"""
    if not available():
        return []
    try:
        resp = requests.get(
            f"{_BASE}/twitter/user/{handle}/tweets",
            headers=_headers(),
            timeout=config.FETCH_TIMEOUT,
        )
        if resp.status_code != 200:
            log.warning("SocialData %s 返回 %s", handle, resp.status_code)
            return []
        tweets = resp.json().get("tweets", []) or []
    except (requests.RequestException, ValueError) as exc:
        log.warning("抓取 @%s 失败：%s", handle, exc)
        return []

    out = []
    for t in tweets[:limit]:
        out.append(
            {
                "handle": handle,
                "text": t.get("full_text") or t.get("text", ""),
                "created_at": t.get("tweet_created_at") or t.get("created_at", ""),
                "url": f"https://x.com/{handle}/status/{t.get('id_str', '')}",
                "likes": t.get("favorite_count", 0),
                "retweets": t.get("retweet_count", 0),
            }
        )
    return out


def search_tweets(query: str, limit: int = 30) -> list[dict]:
    if not available():
        return []
    try:
        resp = requests.get(
            f"{_BASE}/twitter/search",
            headers=_headers(),
            params={"query": query, "type": "Latest"},
            timeout=config.FETCH_TIMEOUT,
        )
        if resp.status_code != 200:
            return []
        return (resp.json().get("tweets", []) or [])[:limit]
    except (requests.RequestException, ValueError) as exc:
        log.warning("搜索推文失败：%s", exc)
        return []
