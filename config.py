"""集中式配置：环境变量、模型、数据源路径、运行参数。

所有脚本从这里读取配置，避免在各处硬编码。凭证只从环境变量读取，
永远不在代码里出现真实 key。
"""
from __future__ import annotations

import datetime as _dt
import os
from pathlib import Path
from zoneinfo import ZoneInfo

# 本地运行时自动加载 .env（CI 里环境变量由 Actions 注入，没有 .env 也没关系）
try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # python-dotenv 未安装或加载失败都不应阻断运行
    pass

# ---------------------------------------------------------------------------
# 路径
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DAILY_FILTERED_DIR = ROOT / "daily_filtered"
FILTERED_NEWS_PATH = ROOT / "filtered_news.json"

# 数据源清单文件
RSS_SOURCES_PATH = DATA_DIR / "rss_feeds.json"
SUBSTACK_SOURCES_PATH = DATA_DIR / "substack_feeds.json"
WECHAT_ACCOUNTS_PATH = DATA_DIR / "wechat_accounts.json"
KOL_LIST_PATH = DATA_DIR / "twitter_kol.json"


def _get(name: str, default: str = "") -> str:
    # 未配置的 GitHub Secret 在 workflow 里会以空字符串注入，空值也要回落到默认值
    return (os.environ.get(name) or "").strip() or default


def _flag(name: str) -> bool:
    """把 '1' / 'true' / 'yes' 视为开启。"""
    return _get(name).lower() in {"1", "true", "yes", "on"}


# ---------------------------------------------------------------------------
# 火山方舟 ARK（豆包）
# ---------------------------------------------------------------------------
VOLC_API_KEY = _get("VOLC_API_KEY")
VOLC_ENDPOINT = _get("VOLC_ENDPOINT", "https://ark.cn-beijing.volces.com/api/v3")
DOUBAO_FILTER_MODEL = _get("DOUBAO_FILTER_MODEL", "doubao-1-5-pro-32k-250115")
DOUBAO_ANALYZE_MODEL = _get("DOUBAO_ANALYZE_MODEL", "doubao-seed-1-6-251015")
# 初筛只做相关性分类，关闭深度思考可大幅提速降本（Seed 系列默认开启）。
# 取值 disabled / enabled / auto；置空字符串以外的值原样传给 ARK 的 thinking.type。
DOUBAO_FILTER_THINKING = _get("DOUBAO_FILTER_THINKING", "disabled")

# ---------------------------------------------------------------------------
# 飞书
# ---------------------------------------------------------------------------
FEISHU_APP_ID = _get("FEISHU_APP_ID")
FEISHU_APP_SECRET = _get("FEISHU_APP_SECRET")
FEISHU_BITABLE_URL = _get("FEISHU_BITABLE_URL")
FEISHU_KNOWLEDGE_BASE_URL = _get("FEISHU_KNOWLEDGE_BASE_URL")
FEISHU_DAILY_REPORT_URL = _get("FEISHU_DAILY_REPORT_URL")
FEISHU_KOL_DIGEST_URL = _get("FEISHU_KOL_DIGEST_URL")
FEISHU_BIWEEKLY_REPORT_URL = _get("FEISHU_BIWEEKLY_REPORT_URL")

# ---------------------------------------------------------------------------
# 抓取 / 运行参数
# ---------------------------------------------------------------------------
try:
    NEWS_HOURS_LIMIT = int(_get("NEWS_HOURS_LIMIT", "24") or "24")
except ValueError:
    NEWS_HOURS_LIMIT = 24

# 单条 feed 抓取超时（秒）与全局并发
FETCH_TIMEOUT = int(_get("FETCH_TIMEOUT", "20") or "20")
FETCH_WORKERS = int(_get("FETCH_WORKERS", "8") or "8")
# 单个源最多保留多少条（数据源里可用 max_items 单独覆盖）
MAX_ITEMS_PER_SOURCE = int(_get("MAX_ITEMS_PER_SOURCE", "40") or "40")

# 豆包初筛的批大小（一次请求评估多少条标题+摘要）
FILTER_BATCH_SIZE = int(_get("FILTER_BATCH_SIZE", "15") or "15")

# 单日产出健康区间（低于下限视为异常，可能是欠费静默降级）
HEALTHY_MIN_ITEMS = int(_get("HEALTHY_MIN_ITEMS", "150") or "150")
HEALTHY_MAX_ITEMS = int(_get("HEALTHY_MAX_ITEMS", "220") or "220")
# 产出低于此值直接判定异常（历史欠费事故时只有 ~20 条）
ANOMALY_FLOOR = int(_get("ANOMALY_FLOOR", "40") or "40")

# Wechat2RSS
WECHAT2RSS_BASE_URL = _get("WECHAT2RSS_BASE_URL")
WECHAT2RSS_TOKEN = _get("WECHAT2RSS_TOKEN")

# 增强模块凭证
VOLC_ASR_APPID = _get("VOLC_ASR_APPID")
VOLC_ASR_TOKEN = _get("VOLC_ASR_TOKEN")
VOLC_ASR_RESOURCE_ID = _get("VOLC_ASR_RESOURCE_ID")
PODCAST_ADMIN_EMAIL = _get("PODCAST_ADMIN_EMAIL")
SOCIALDATA_API_KEY = _get("SOCIALDATA_API_KEY")
AI_NEWS_RADAR_DEPLOY_KEY = _get("AI_NEWS_RADAR_DEPLOY_KEY")
AI_TO_C_MODEL = _get("AI_TO_C_MODEL")

# ---------------------------------------------------------------------------
# 开关
# ---------------------------------------------------------------------------
DISABLE_FEISHU_WRITE = _flag("DISABLE_FEISHU_WRITE")


# 日报 Markdown 存档目录（随 workflow commit 回仓库，不配飞书也能看日报）
REPORTS_DIR = ROOT / "reports"

# 飞书群机器人（可选，最轻量的推送方式：群设置 → 群机器人 → 自定义机器人）
FEISHU_WEBHOOK_URL = _get("FEISHU_WEBHOOK_URL")
FEISHU_WEBHOOK_SECRET = _get("FEISHU_WEBHOOK_SECRET")  # 机器人开启「签名校验」时填


# 报告日期按北京时间计（GitHub 定时任务可能延迟数小时，UTC 日期会错位）
REPORT_TZ = ZoneInfo(_get("REPORT_TZ", "Asia/Shanghai") or "Asia/Shanghai")


def today() -> _dt.date:
    return _dt.datetime.now(REPORT_TZ).date()


def missing(*names: str) -> list[str]:
    """返回未配置（为空）的环境变量名。"""
    return [n for n in names if not _get(n)]


def has_ark() -> bool:
    return bool(VOLC_API_KEY)


def has_feishu() -> bool:
    return bool(FEISHU_APP_ID and FEISHU_APP_SECRET)
