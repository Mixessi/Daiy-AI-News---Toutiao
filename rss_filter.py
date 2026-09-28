"""主入口：抓 RSS → 24h 窗过滤 → 豆包初筛 → filtered_news.json → 写飞书多维表格。

运行：
    python rss_filter.py                 # 完整跑（写飞书）
    DISABLE_FEISHU_WRITE=1 python rss_filter.py   # 安全试跑，只产出本地 JSON

初筛 Prompt 就写在本文件里（PROMPT 常量），便于直接编辑。
"""
from __future__ import annotations

import json
import sys

import config
from doubao_client import DoubaoClient
from feed_fetcher import fetch_recent
from logging_utils import (
    AccountOverdueError,
    alert_missing_config,
    banner,
    get_logger,
    gha_error,
    gha_warning,
)

log = get_logger("rss_filter")

# ---------------------------------------------------------------------------
# 初筛 Prompt —— 面向今日头条 / 番茄小说 / 红果短剧等产品视角
# ---------------------------------------------------------------------------
FILTER_SYSTEM_PROMPT = """你是字节跳动内容业务的资深战略分析师，为「今日头条、番茄小说、红果短剧」等产品做每日情报初筛。
你的任务：从一批新闻标题+摘要中，判断每条是否与我们的战略方向相关，只保留高价值信息。

【战略相关】的范围（命中任一即相关）：
- AI 大模型 / 生成式 AI / AI 应用与产品（尤其内容生成、推荐、Agent）
- 短视频、直播、内容社区、信息流推荐
- 网络文学、网文出海、AI 写作
- 短剧、微短剧、互动影视
- 上述领域的重要公司动态、融资、监管政策、关键人物观点、技术突破

【不相关】：与上述无关的纯消费电子评测、体育、娱乐八卦、一般财经、无AI要素的通用软件等。

对每条新闻，给出：
- relevant: true/false
- score: 0-10 的相关性/重要性评分（10 最高）
- reason: 一句话中文理由（为何相关/不相关，及对我们产品的潜在意义）

只返回 JSON 数组，每个元素形如：
{"index": <输入序号>, "relevant": true, "score": 8, "reason": "..."}
不要输出数组以外的任何内容。"""


def _build_user_prompt(batch: list[dict], start_index: int) -> str:
    lines = []
    for i, it in enumerate(batch):
        idx = start_index + i
        lines.append(f"[{idx}] 标题：{it['title']}\n    来源：{it['source']}\n    摘要：{it.get('summary','')[:300]}")
    return "待判断的新闻：\n\n" + "\n\n".join(lines)


def filter_news(items: list[dict]) -> list[dict]:
    """用豆包对新闻做相关性初筛，返回保留下来的条目（带 score/reason）。"""
    if not items:
        return []
    if not config.has_ark():
        raise ValueError("VOLC_API_KEY 未配置，无法初筛。")

    client = DoubaoClient()
    kept: list[dict] = []
    batch_size = config.FILTER_BATCH_SIZE

    total_batches = (len(items) + batch_size - 1) // batch_size
    for b in range(total_batches):
        start = b * batch_size
        batch = items[start : start + batch_size]
        user_prompt = _build_user_prompt(batch, start)
        try:
            result = client.chat_json(
                [
                    {"role": "system", "content": FILTER_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                model=config.DOUBAO_FILTER_MODEL,
                temperature=0.2,
            )
        except AccountOverdueError:
            # 欠费：致命，直接向上抛（由 main 统一处理并让 workflow 标红）
            raise
        except Exception as exc:
            # 单批失败：容错但告警，保守保留本批（宁可多留，不可静默丢弃）
            log.warning("第 %d/%d 批初筛失败，保守保留本批: %s", b + 1, total_batches, exc)
            gha_warning(f"初筛第 {b+1} 批失败: {exc}")
            for it in batch:
                kept.append({**it, "score": 5, "reason": "初筛异常，保守保留"})
            continue

        if not isinstance(result, list):
            log.warning("第 %d 批返回非数组，保守保留本批", b + 1)
            for it in batch:
                kept.append({**it, "score": 5, "reason": "初筛结果解析失败，保守保留"})
            continue

        by_index = {r.get("index"): r for r in result if isinstance(r, dict)}
        for i, it in enumerate(batch):
            idx = start + i
            verdict = by_index.get(idx, {})
            if verdict.get("relevant"):
                kept.append(
                    {
                        **it,
                        "score": verdict.get("score", 5),
                        "reason": verdict.get("reason", ""),
                    }
                )
        log.info("初筛进度 %d/%d 批，累计保留 %d 条", b + 1, total_batches, len(kept))

    kept.sort(key=lambda x: x.get("score", 0), reverse=True)
    return kept


def health_check(kept: list[dict]) -> None:
    """产出健康检查：低于地板值高度怀疑欠费静默降级，醒目告警。"""
    n = len(kept)
    if n < config.ANOMALY_FLOOR:
        banner(
            log,
            f"产出异常偏低：仅 {n} 条（正常 {config.HEALTHY_MIN_ITEMS}~{config.HEALTHY_MAX_ITEMS}）",
            [
                "高度怀疑：火山账户欠费导致静默降级，或多数源抓取失败。",
                "请检查：VOLC 余额、ARK 报错日志、网络与源可用性。",
            ],
            level="error",
        )
        gha_error(f"当日产出仅 {n} 条，远低于健康区间，疑似欠费/抓取异常。")
    elif n < config.HEALTHY_MIN_ITEMS:
        log.warning("产出 %d 条，略低于健康下限 %d，请留意。", n, config.HEALTHY_MIN_ITEMS)
        gha_warning(f"当日产出 {n} 条，略低于健康下限 {config.HEALTHY_MIN_ITEMS}。")
    else:
        log.info("产出 %d 条，处于健康区间。", n)


def write_outputs(kept: list[dict]) -> None:
    # 1) 本地 JSON
    config.FILTERED_NEWS_PATH.write_text(
        json.dumps(kept, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log.info("已写出 %s（%d 条）", config.FILTERED_NEWS_PATH.name, len(kept))

    # 2) 飞书多维表格（可关闭）
    if config.DISABLE_FEISHU_WRITE:
        log.info("DISABLE_FEISHU_WRITE=1，跳过写飞书。")
        return
    if not config.has_feishu() or not config.FEISHU_BITABLE_URL:
        log.warning("飞书未配置或缺 FEISHU_BITABLE_URL，跳过写多维表格。")
        return

    from feishu_bitable import FeishuBitable, news_items_to_records

    bitable = FeishuBitable()
    records = news_items_to_records(kept)
    bitable.replace_all(records)  # 幂等：先清空再写


def main() -> int:
    log.info("=== RSS 初筛流水线开始 ===")
    lacking = config.missing("VOLC_API_KEY")
    if lacking:
        # 先检查再抓取：缺 key 时直接给出清晰指引，而不是抓完再抛 traceback
        alert_missing_config(log, lacking, "调用豆包初筛")
        return 1
    try:
        raw = fetch_recent()
        kept = filter_news(raw)
        health_check(kept)
        write_outputs(kept)
    except AccountOverdueError:
        # 欠费告警已在客户端打印；这里确保非零退出让 workflow 标红
        log.error("因火山账户欠费中止（非零退出）。")
        return 2
    log.info("=== 完成：保留 %d 条 ===", len(kept))
    return 0


if __name__ == "__main__":
    sys.exit(main())
