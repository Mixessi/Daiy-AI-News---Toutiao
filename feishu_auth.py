"""飞书鉴权与 URL 解析工具（被 feishu_bitable / feishu_integration 复用）。"""
from __future__ import annotations

import re
import time
from urllib.parse import parse_qs, urlparse

import requests

import config
from logging_utils import get_logger

log = get_logger("feishu")

_FEISHU_HOST = "https://open.feishu.cn"
_token_cache: dict[str, tuple[str, float]] = {}


def get_tenant_access_token() -> str:
    """获取 tenant_access_token，带简单缓存（有效期内复用）。"""
    cached = _token_cache.get("tenant")
    if cached and cached[1] > time.time() + 60:
        return cached[0]

    if not config.has_feishu():
        raise ValueError("FEISHU_APP_ID / FEISHU_APP_SECRET 未配置。")

    resp = requests.post(
        f"{_FEISHU_HOST}/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": config.FEISHU_APP_ID, "app_secret": config.FEISHU_APP_SECRET},
        timeout=config.FETCH_TIMEOUT,
    )
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"获取飞书 token 失败: {data}")
    token = data["tenant_access_token"]
    _token_cache["tenant"] = (token, time.time() + data.get("expire", 7200))
    return token


def auth_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {get_tenant_access_token()}",
        "Content-Type": "application/json; charset=utf-8",
    }


def parse_bitable_url(url: str) -> tuple[str, str]:
    """从多维表格 URL 解析 (app_token, table_id)。

    支持形如：
      https://xxx.feishu.cn/base/<app_token>?table=<table_id>&view=<view_id>
      https://xxx.feishu.cn/wiki/<wiki_token>?table=<table_id>   （wiki 需换算，见下）
    """
    if not url:
        raise ValueError("多维表格 URL 为空。")
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    table_id = (qs.get("table") or [""])[0]

    m = re.search(r"/(?:base|wiki)/([A-Za-z0-9]+)", parsed.path)
    if not m:
        raise ValueError(f"无法从 URL 解析 app_token: {url}")
    token = m.group(1)

    # wiki 节点需要用 wiki API 换算成真正的 obj_token（bitable app_token）
    if "/wiki/" in parsed.path:
        token = _wiki_node_to_obj_token(token)
    return token, table_id


def _wiki_node_to_obj_token(node_token: str) -> str:
    resp = requests.get(
        f"{_FEISHU_HOST}/open-apis/wiki/v2/spaces/get_node",
        headers=auth_headers(),
        params={"token": node_token},
        timeout=config.FETCH_TIMEOUT,
    )
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"wiki 节点换算失败: {data}")
    return data["data"]["node"]["obj_token"]


def extract_doc_id(url: str) -> str:
    """从飞书文档 URL 解析 document_id（docx）。"""
    if not url:
        raise ValueError("文档 URL 为空。")
    m = re.search(r"/(?:docx|docs|wiki)/([A-Za-z0-9]+)", urlparse(url).path)
    if not m:
        raise ValueError(f"无法从 URL 解析文档 ID: {url}")
    token = m.group(1)
    if "/wiki/" in url:
        token = _wiki_node_to_obj_token(token)
    return token


def api_host() -> str:
    return _FEISHU_HOST
