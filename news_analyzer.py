"""深度分析：读初筛结果 → 豆包生成结构化日报 → 写飞书日报文档。

运行：
    python news_analyzer.py --feishu          # 分析并写飞书日报
    python news_analyzer.py                    # 只本地产出 analysis_output.json / 日报 markdown
    python news_analyzer.py --model doubao-1-5-pro-32k-250115   # 指定模型

增强模块（缺 key 自动跳过、不报错）：
    - 播客转录（火山 ASR）via podcast_processor
    - Twitter 舆情 via twitter_opinions
分析 Prompt 就写在本文件里（ANALYZE_PROMPT），便于直接编辑。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import config
from doubao_client import DoubaoClient
from logging_utils import AccountOverdueError, alert_missing_config, get_logger, gha_error, gha_warning

log = get_logger("news_analyzer")

ANALYZE_SYSTEM_PROMPT = """你是字节跳动内容业务的首席 AI 战略分析师。基于今日初筛后的高相关新闻，
撰写一份面向管理层的《每日 AI 情报日报》。产品视角覆盖今日头条、番茄小说、红果短剧。

要求：
1. 先给「今日要点」：3-6 条最重要的判断，每条一句话，点明"发生了什么 + 对我们意味着什么"。
2. 分主题归纳：大模型/技术、内容生成与AIGC应用、短视频与推荐、网文与短剧、政策与行业、竞品动态。
   每个主题下列相关新闻要点（带来源），并给一句战略解读。没有内容的主题可省略。
3. 结尾给「值得跟进」：2-4 个建议关注/深挖的方向。
用简洁专业的中文，Markdown 格式（# 标题、## 二级、- 列表）。不要编造未提供的事实。"""


def _load_filtered() -> list[dict]:
    if not config.FILTERED_NEWS_PATH.exists():
        log.error("未找到 %s，请先运行 rss_filter.py。", config.FILTERED_NEWS_PATH.name)
        return []
    return json.loads(config.FILTERED_NEWS_PATH.read_text(encoding="utf-8"))


def _compose_news_digest(items: list[dict], limit: int = 120) -> str:
    lines = []
    for it in items[:limit]:
        lines.append(
            f"- [{it.get('source','')}] {it.get('title','')} "
            f"(score={it.get('score','')}) {it.get('url','')}\n  摘要：{it.get('summary','')[:200]}"
        )
    return "\n".join(lines)


def analyze(items: list[dict], model: str, extras: str = "") -> str:
    if not items:
        return "# 今日无相关新闻\n\n初筛结果为空。"
    if not config.has_ark():
        raise ValueError("VOLC_API_KEY 未配置，无法深度分析。")

    client = DoubaoClient()
    today = config.today().isoformat()
    user = (
        f"日期：{today}\n今日初筛保留 {len(items)} 条。以下为新闻清单：\n\n"
        + _compose_news_digest(items)
    )
    if extras:
        user += f"\n\n【补充情报】\n{extras}"

    report = client.chat(
        [
            {"role": "system", "content": ANALYZE_SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
        model=model,
        temperature=0.4,
        max_tokens=4000,
    )
    header = f"# AI 情报日报 · {today}\n\n> 初筛保留 {len(items)} 条 · 分析模型 {model}\n\n"
    return header + report.strip()


def _gather_extras() -> str:
    """收集增强模块产出（缺 key 自动跳过）。"""
    chunks = []
    # 播客转录
    try:
        from podcast_processor import get_podcast_highlights

        pod = get_podcast_highlights()
        if pod:
            chunks.append("播客要点：\n" + pod)
    except Exception as exc:
        log.info("播客增强跳过：%s", exc)

    # Twitter 舆情
    try:
        from twitter_opinions import get_opinion_highlights

        tw = get_opinion_highlights()
        if tw:
            chunks.append("Twitter 舆情：\n" + tw)
    except Exception as exc:
        log.info("Twitter 增强跳过：%s", exc)

    return "\n\n".join(chunks)


def _save_report(report_md: str, date_str: str) -> str:
    """存档日报 Markdown 到 reports/，并写入 GitHub Actions 运行摘要页。"""
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = config.REPORTS_DIR / f"{date_str}.md"
    path.write_text(report_md + "\n", encoding="utf-8")
    log.info("已写出 %s", path.relative_to(config.ROOT))

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(report_md + "\n")
    return str(path.relative_to(config.ROOT))


def _report_link(rel_path: str) -> str:
    """GitHub 上该日报文件的链接（仅在 Actions 中可得）。"""
    server = os.environ.get("GITHUB_SERVER_URL")
    repo = os.environ.get("GITHUB_REPOSITORY")
    ref = os.environ.get("GITHUB_REF_NAME")
    if server and repo and ref:
        return f"{server}/{repo}/blob/{ref}/{rel_path}"
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description="深度分析并生成 AI 日报")
    parser.add_argument("--feishu", action="store_true", help="写入飞书日报文档")
    parser.add_argument("--model", default=config.DOUBAO_ANALYZE_MODEL, help="指定分析模型 ID")
    args = parser.parse_args()

    log.info("=== 深度分析开始（模型 %s）===", args.model)
    lacking = config.missing("VOLC_API_KEY")
    if lacking:
        alert_missing_config(log, lacking, "调用豆包深度分析")
        return 1
    items = _load_filtered()

    extras = _gather_extras()

    try:
        report_md = analyze(items, model=args.model, extras=extras)
    except AccountOverdueError:
        log.error("因火山账户欠费中止（非零退出）。")
        return 2

    # 本地产出
    date_str = config.today().isoformat()
    out_path = config.ROOT / "analysis_output.json"
    out_path.write_text(
        json.dumps({"date": date_str, "report_markdown": report_md}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info("已写出 analysis_output.json")
    rel_path = _save_report(report_md, date_str)

    # 写飞书
    exit_code = 0
    if args.feishu:
        if config.DISABLE_FEISHU_WRITE:
            log.info("DISABLE_FEISHU_WRITE=1，跳过写飞书日报。")
        elif not (config.has_feishu() and config.FEISHU_DAILY_REPORT_URL):
            log.warning("飞书未配置或缺 FEISHU_DAILY_REPORT_URL，跳过写日报文档。")
            gha_warning("缺 FEISHU_DAILY_REPORT_URL，未写飞书日报。")
        else:
            from feishu_integration import FeishuDoc

            try:
                FeishuDoc(config.FEISHU_DAILY_REPORT_URL).append_markdown(report_md)
                log.info("已写入飞书日报文档。")
            except Exception as exc:
                # 写文档失败不应拖垮群推送与归档提交，但要让 workflow 标红
                log.error("写飞书日报文档失败：%s", exc)
                gha_error(f"写飞书日报文档失败：{exc}")
                exit_code = 1

        # 飞书群机器人推送（可选，只需一个 webhook 地址）
        if not config.DISABLE_FEISHU_WRITE and config.FEISHU_WEBHOOK_URL:
            from feishu_webhook import push_report

            link = config.FEISHU_DAILY_REPORT_URL or _report_link(rel_path)
            push_report(f"AI 情报日报 · {date_str}", report_md, link=link)

    log.info("=== 深度分析完成 ===")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
