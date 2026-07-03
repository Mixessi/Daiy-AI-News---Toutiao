"""kol_digest workflow 入口：抓 Twitter KOL 动态 → 豆包摘要 → 写飞书。

需要 SOCIALDATA_API_KEY（抓推文）与 VOLC_API_KEY（摘要）。缺 SocialData 则优雅退出。
写飞书需 FEISHU_KOL_DIGEST_URL。
"""
from __future__ import annotations

import datetime as _dt
import json
import sys

import config
from doubao_client import DoubaoClient
from logging_utils import AccountOverdueError, get_logger
from twitter_fetcher import available, fetch_user_tweets

log = get_logger("kol_digest")

DIGEST_PROMPT = """你是 AI 领域情报分析师。下面是若干 AI KOL 最近的推文，请生成一份中文《KOL 动态摘要》：
按人物/主题归纳最值得关注的观点与信号，指出对内容/AI 产品的潜在影响。Markdown 格式，简洁。"""


def _load_kols() -> list[dict]:
    if not config.KOL_LIST_PATH.exists():
        return []
    return json.loads(config.KOL_LIST_PATH.read_text(encoding="utf-8")).get("kols", [])


def main() -> int:
    log.info("=== KOL Digest 开始 ===")
    if not available():
        log.warning("未配置 SOCIALDATA_API_KEY，跳过 KOL Digest（正常退出）。")
        return 0

    kols = _load_kols()
    collected = []
    for k in kols:
        tweets = fetch_user_tweets(k["handle"], limit=15)
        for t in tweets:
            collected.append(f"@{k['handle']}({k.get('name','')}): {t['text'][:280]}")
    if not collected:
        log.warning("未抓到 KOL 推文，跳过。")
        return 0

    if not config.has_ark():
        log.warning("未配置 VOLC_API_KEY，无法摘要。")
        return 0

    client = DoubaoClient()
    today = _dt.date.today().isoformat()
    try:
        digest = client.chat(
            [
                {"role": "system", "content": DIGEST_PROMPT},
                {"role": "user", "content": f"日期：{today}\n\n" + "\n".join(collected[:200])},
            ],
            model=config.DOUBAO_ANALYZE_MODEL,
            temperature=0.4,
            max_tokens=3000,
        )
    except AccountOverdueError:
        log.error("因火山账户欠费中止。")
        return 2

    report = f"# KOL 动态摘要 · {today}\n\n{digest.strip()}"
    (config.ROOT / "kol_digest_output.md").write_text(report, encoding="utf-8")
    log.info("已写出 kol_digest_output.md")

    if config.DISABLE_FEISHU_WRITE:
        log.info("DISABLE_FEISHU_WRITE=1，跳过写飞书。")
    elif config.has_feishu() and config.FEISHU_KOL_DIGEST_URL:
        from feishu_integration import FeishuDoc

        FeishuDoc(config.FEISHU_KOL_DIGEST_URL).append_markdown(report)
        log.info("已写入飞书 KOL 文档。")
    else:
        log.warning("缺 FEISHU_KOL_DIGEST_URL，未写飞书。")

    log.info("=== KOL Digest 完成 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
