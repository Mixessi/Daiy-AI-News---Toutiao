"""统一日志与醒目告警。

设计要点（来自交接文档的历史事故教训）：大模型/网络失败要容错，
但**必须显式告警**——尤其火山账户欠费（403 AccountOverdueError）时，
原系统曾静默降级：workflow 显示 success，但当天只抓到 20 来条
（正常 150~220 条）。这里提供醒目的横幅告警，并在 GitHub Actions 中
额外输出 `::error::` 注解让该步骤/整个 run 标红。
"""
from __future__ import annotations

import logging
import os
import sys

_CONFIGURED = False


def get_logger(name: str = "ai_news") -> logging.Logger:
    global _CONFIGURED
    if not _CONFIGURED:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
            stream=sys.stdout,
        )
        _CONFIGURED = True
    return logging.getLogger(name)


def _in_github_actions() -> bool:
    return os.environ.get("GITHUB_ACTIONS", "").lower() == "true"


def gha_error(message: str) -> None:
    """在 GitHub Actions 里输出错误注解（让步骤标红）。本地运行则忽略。"""
    if _in_github_actions():
        # 单行，去掉换行以符合 workflow command 语法
        print(f"::error::{message.replace(chr(10), ' ')}")


def gha_warning(message: str) -> None:
    if _in_github_actions():
        print(f"::warning::{message.replace(chr(10), ' ')}")


def banner(logger: logging.Logger, title: str, lines: list[str], level: str = "error") -> None:
    """打印一个醒目的横幅告警。"""
    width = 72
    bar = "!" * width
    log = getattr(logger, level, logger.error)
    log(bar)
    log(f"!! {title}".ljust(width))
    for ln in lines:
        log(f"!! {ln}".ljust(width))
    log(bar)


class AccountOverdueError(RuntimeError):
    """火山方舟账户欠费（403 AccountOverdueError）。

    这是**致命**错误：不能静默降级。捕获到它应让整个 workflow 标红退出，
    而不是继续跑出一份残缺的日报。
    """


def alert_overdue(logger: logging.Logger, detail: str = "") -> None:
    banner(
        logger,
        "火山方舟账户欠费 —— AccountOverdueError（致命）",
        [
            "大模型调用被拒（HTTP 403 / AccountOverdue）。",
            "系统将停止，避免静默产出残缺日报（历史事故根因）。",
            "处理：登录火山控制台充值，并设置余额告警 / 自动续费。",
            f"detail: {detail}" if detail else "",
        ],
        level="error",
    )
    gha_error("VOLC ARK AccountOverdueError: 火山方舟账户欠费，流水线中止。请充值。")


def alert_missing_config(logger: logging.Logger, names: list[str], purpose: str) -> None:
    """必需配置缺失：打印横幅 + 让 workflow 标红，并告诉用户去哪里配。"""
    banner(
        logger,
        f"缺少必需配置，无法{purpose}",
        [f"未配置：{', '.join(names)}"]
        + [
            "GitHub：Settings → Secrets and variables → Actions → New repository secret",
            "本地：复制 .env.example 为 .env 并填写",
        ],
        level="error",
    )
    gha_error(f"缺少必需配置 {', '.join(names)}，无法{purpose}。请在仓库 Secrets 中配置。")
