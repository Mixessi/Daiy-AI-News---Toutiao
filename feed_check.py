"""数据源体检：逐个抓取 data/*.json 里的 feed，打印可用性表格。

不调用大模型、不写飞书，只做网络 + 解析检查，用于维护数据源清单：
    python feed_check.py            # 检查全部源
    python feed_check.py --strict   # 有源不可用时非零退出

输出每个源的状态、条目数、最新一条的时间，便于剔除失效源。
"""
from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import feedparser

import config
from feed_fetcher import _download, _entry_timestamp, _load_feed_file
from logging_utils import get_logger, gha_warning
from wechat2rss_sync import sync_wechat_feeds

log = get_logger("feed_check")


def check_one(source: dict) -> dict:
    name = source.get("name", source["url"])
    t0 = time.time()
    try:
        parsed = feedparser.parse(_download(source["url"]))
    except Exception as exc:
        return {"name": name, "ok": False, "entries": 0, "latest": "", "note": str(exc)[:80]}
    entries = parsed.entries
    if not entries:
        note = str(getattr(parsed, "bozo_exception", "")) or "无条目"
        return {"name": name, "ok": False, "entries": 0, "latest": "", "note": note[:80]}
    stamps = [ts for ts in (_entry_timestamp(e) for e in entries) if ts]
    latest = datetime.fromtimestamp(max(stamps), tz=timezone.utc) if stamps else None
    age_days = (time.time() - max(stamps)) / 86400 if stamps else None
    note = f"{time.time() - t0:.1f}s"
    if latest is None:
        note += " 无发布时间"
    elif age_days > 30:
        note += f" 已 {age_days:.0f} 天未更新"
    return {
        "name": name,
        "ok": True,
        "entries": len(entries),
        "latest": latest.strftime("%Y-%m-%d %H:%M") if latest else "-",
        "note": note,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="数据源体检")
    parser.add_argument("--strict", action="store_true", help="有源不可用时非零退出")
    args = parser.parse_args()

    groups = {
        "RSS": _load_feed_file(config.RSS_SOURCES_PATH),
        "Substack": _load_feed_file(config.SUBSTACK_SOURCES_PATH),
        "公众号": sync_wechat_feeds(),
    }
    bad = 0
    for group, sources in groups.items():
        if not sources:
            print(f"\n## {group}: 无源")
            continue
        with ThreadPoolExecutor(max_workers=config.FETCH_WORKERS) as pool:
            results = list(pool.map(check_one, sources))
        good = sum(r["ok"] for r in results)
        print(f"\n## {group}: {good}/{len(results)} 可用")
        for r in sorted(results, key=lambda r: (r["ok"], r["name"])):
            mark = "OK  " if r["ok"] else "FAIL"
            print(f"{mark} {r['name'][:40]:<40} {r['entries']:>4} 条  最新 {r['latest']:<16} {r['note']}")
        failed = [r["name"] for r in results if not r["ok"]]
        bad += len(failed)
        if failed:
            gha_warning(f"{group} 不可用源 {len(failed)} 个: {', '.join(failed)}")

    return 1 if (args.strict and bad) else 0


if __name__ == "__main__":
    sys.exit(main())
