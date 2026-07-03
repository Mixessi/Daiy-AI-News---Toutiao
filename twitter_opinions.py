"""Twitter 舆情增强：围绕 AI 关键词抓取讨论，供 news_analyzer 补充情报。

需要 SOCIALDATA_API_KEY，缺则返回空串。
"""
from __future__ import annotations

import config
from logging_utils import get_logger
from twitter_fetcher import available, search_tweets

log = get_logger("twitter.opinions")

# 舆情监测关键词，可按需增减
OPINION_QUERIES = [
    "generative AI",
    "short drama AI",
    "AI recommendation feed",
    "AI 短剧",
    "AI 网文",
]


def get_opinion_highlights(max_per_query: int = 5) -> str:
    if not available():
        log.info("未配置 SOCIALDATA_API_KEY，跳过 Twitter 舆情。")
        return ""

    blocks = []
    for q in OPINION_QUERIES:
        tweets = search_tweets(q, limit=max_per_query)
        if not tweets:
            continue
        lines = [f"  · {t.get('full_text') or t.get('text','')}".replace("\n", " ")[:200] for t in tweets]
        blocks.append(f"[{q}]\n" + "\n".join(lines))
    return "\n\n".join(blocks)
