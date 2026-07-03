"""归档当天初筛结果到 daily_filtered/YYYY-MM-DD.json。

由 daily_news workflow 在初筛之后调用，产物随后被 commit 回仓库，
形成可追溯的每日快照。
"""
from __future__ import annotations

import datetime as _dt
import json
import sys

import config
from logging_utils import get_logger

log = get_logger("archive")


def archive(date_str: str | None = None) -> str:
    if not config.FILTERED_NEWS_PATH.exists():
        log.error("未找到 %s，无法归档。", config.FILTERED_NEWS_PATH.name)
        raise SystemExit(1)

    date_str = date_str or _dt.date.today().isoformat()
    config.DAILY_FILTERED_DIR.mkdir(parents=True, exist_ok=True)
    target = config.DAILY_FILTERED_DIR / f"{date_str}.json"

    items = json.loads(config.FILTERED_NEWS_PATH.read_text(encoding="utf-8"))
    snapshot = {
        "date": date_str,
        "count": len(items),
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "items": items,
    }
    target.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("已归档 %s（%d 条）", target, len(items))
    return str(target)


if __name__ == "__main__":
    archive(sys.argv[1] if len(sys.argv) > 1 else None)
