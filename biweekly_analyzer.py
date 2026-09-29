"""biweekly workflow 入口：汇总近 14 天 daily_filtered 归档 → 豆包生成双周深度报告 → 写飞书。

读 daily_filtered/*.json 最近 14 天，聚合后交给豆包做趋势/主题层面的深度分析。
写飞书需 FEISHU_BIWEEKLY_REPORT_URL。
"""
from __future__ import annotations

import datetime as _dt
import json
import sys

import config
from doubao_client import DoubaoClient
from logging_utils import AccountOverdueError, get_logger

log = get_logger("biweekly")

BIWEEKLY_PROMPT = """你是字节跳动内容业务的首席战略分析师。下面是过去两周每日 AI 情报的汇总。
请撰写一份《双周 AI 深度报告》：
1. 两周主线：本阶段最重要的 3-5 个趋势/事件主线，each 说明演进过程与判断。
2. 主题深挖：大模型能力、AIGC 内容生产、短视频/推荐、网文与短剧、政策与竞争格局。
3. 对我们（今日头条/番茄小说/红果短剧）的机会与风险。
4. 下阶段建议关注的信号。
用专业中文，Markdown 格式，有观点、有取舍，避免流水账。"""


def _load_recent_archives(days: int = 14) -> list[dict]:
    if not config.DAILY_FILTERED_DIR.exists():
        return []
    cutoff = config.today() - _dt.timedelta(days=days)
    items = []
    for path in sorted(config.DAILY_FILTERED_DIR.glob("*.json")):
        try:
            date = _dt.date.fromisoformat(path.stem)
        except ValueError:
            continue
        if date < cutoff:
            continue
        try:
            snap = json.loads(path.read_text(encoding="utf-8"))
            items.append(snap)
        except Exception:
            continue
    return items


def _digest(snaps: list[dict], limit_per_day: int = 40) -> str:
    lines = []
    for snap in snaps:
        lines.append(f"## {snap.get('date','')}（{snap.get('count',0)} 条）")
        for it in (snap.get("items") or [])[:limit_per_day]:
            lines.append(f"- [{it.get('source','')}] {it.get('title','')} (score={it.get('score','')})")
    return "\n".join(lines)


def main() -> int:
    log.info("=== 双周报开始 ===")
    snaps = _load_recent_archives()
    if not snaps:
        log.warning("近 14 天无归档数据，跳过。")
        return 0
    if not config.has_ark():
        log.warning("未配置 VOLC_API_KEY，无法分析。")
        return 0

    client = DoubaoClient(timeout=600)  # 深度思考 + 长文输出，单次请求可能数分钟
    today = config.today().isoformat()
    try:
        report_body = client.chat(
            [
                {"role": "system", "content": BIWEEKLY_PROMPT},
                {"role": "user", "content": f"截至 {today} 的近两周情报：\n\n" + _digest(snaps)},
            ],
            model=config.DOUBAO_ANALYZE_MODEL,
            temperature=0.4,
            max_tokens=6000,
        )
    except AccountOverdueError:
        log.error("因火山账户欠费中止。")
        return 2

    report = f"# 双周 AI 深度报告 · 截至 {today}\n\n> 覆盖 {len(snaps)} 天归档\n\n{report_body.strip()}"
    (config.ROOT / "biweekly_output.md").write_text(report, encoding="utf-8")
    log.info("已写出 biweekly_output.md")

    if config.DISABLE_FEISHU_WRITE:
        log.info("DISABLE_FEISHU_WRITE=1，跳过写飞书。")
    elif config.has_feishu() and config.FEISHU_BIWEEKLY_REPORT_URL:
        from feishu_integration import FeishuDoc

        FeishuDoc(config.FEISHU_BIWEEKLY_REPORT_URL).append_markdown(report)
        log.info("已写入飞书双周报文档。")
    else:
        log.warning("缺 FEISHU_BIWEEKLY_REPORT_URL，未写飞书。")

    log.info("=== 双周报完成 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
