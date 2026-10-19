"""飞书多维表格 API 封装。

主要用于把初筛结果写入表格。为保证**幂等**（交接文档要求：写前先 clear 再重写），
提供 clear_all_records + batch_create。
"""
from __future__ import annotations

import time

import requests

import config
from feishu_auth import api_host, auth_headers, parse_bitable_url
from logging_utils import get_logger

log = get_logger("feishu.bitable")


class FeishuBitable:
    def __init__(self, url: str | None = None):
        self.url = url or config.FEISHU_BITABLE_URL
        self.app_token, self.table_id = parse_bitable_url(self.url)
        self._base = f"{api_host()}/open-apis/bitable/v1/apps/{self.app_token}/tables/{self.table_id}"

    # ---- 读 --------------------------------------------------------------
    def list_record_ids(self) -> list[str]:
        ids: list[str] = []
        page_token = ""
        while True:
            params = {"page_size": 500}
            if page_token:
                params["page_token"] = page_token
            resp = requests.get(
                f"{self._base}/records", headers=auth_headers(), params=params, timeout=config.FETCH_TIMEOUT
            )
            data = resp.json()
            if data.get("code") != 0:
                raise RuntimeError(f"列举记录失败: {data}")
            items = data.get("data", {}).get("items", []) or []
            ids.extend(rec["record_id"] for rec in items)
            if not data["data"].get("has_more"):
                break
            page_token = data["data"].get("page_token", "")
        return ids

    # ---- 字段（列）：缺失的列自动创建，免去手工建表 ----------------------
    def list_field_names(self) -> set[str]:
        names: set[str] = set()
        page_token = ""
        while True:
            params = {"page_size": 100}
            if page_token:
                params["page_token"] = page_token
            resp = requests.get(
                f"{self._base}/fields", headers=auth_headers(), params=params, timeout=config.FETCH_TIMEOUT
            )
            data = resp.json()
            if data.get("code") != 0:
                raise RuntimeError(f"列举字段失败: {data}")
            names.update(f["field_name"] for f in data.get("data", {}).get("items", []) or [])
            if not data["data"].get("has_more"):
                return names
            page_token = data["data"].get("page_token", "")

    def ensure_fields(self, schema: dict[str, int]) -> list[str]:
        """确保表格含 schema 中的列（列名 → 飞书字段类型），缺失的自动创建。"""
        existing = self.list_field_names()
        created = []
        for name, field_type in schema.items():
            if name in existing:
                continue
            resp = requests.post(
                f"{self._base}/fields",
                headers=auth_headers(),
                json={"field_name": name, "type": field_type},
                timeout=config.FETCH_TIMEOUT,
            )
            data = resp.json()
            if data.get("code") != 0:
                raise RuntimeError(f"创建字段「{name}」失败: {data}")
            created.append(name)
        if created:
            log.info("已在多维表格中自动创建列：%s", "、".join(created))
        return created

    # ---- 删（清空，保证幂等）--------------------------------------------
    def clear_all_records(self) -> int:
        ids = self.list_record_ids()
        deleted = 0
        for i in range(0, len(ids), 500):
            batch = ids[i : i + 500]
            resp = requests.post(
                f"{self._base}/records/batch_delete",
                headers=auth_headers(),
                json={"records": batch},
                timeout=config.FETCH_TIMEOUT,
            )
            data = resp.json()
            if data.get("code") != 0:
                raise RuntimeError(f"批量删除失败: {data}")
            deleted += len(batch)
        if deleted:
            log.info("已清空多维表格旧记录 %d 条", deleted)
        return deleted

    # ---- 写 --------------------------------------------------------------
    def batch_create(self, records: list[dict]) -> int:
        """records: [{fields: {...}}, ...]。分批（每批 ≤500）写入。"""
        created = 0
        for i in range(0, len(records), 500):
            batch = records[i : i + 500]
            for attempt in range(1, 4):
                resp = requests.post(
                    f"{self._base}/records/batch_create",
                    headers=auth_headers(),
                    json={"records": batch},
                    timeout=config.FETCH_TIMEOUT,
                )
                data = resp.json()
                if data.get("code") == 0:
                    created += len(batch)
                    break
                if data.get("code") in (99991663, 99991661):  # token 过期等，重试
                    time.sleep(2 * attempt)
                    continue
                raise RuntimeError(f"批量写入失败: {data}")
        log.info("已写入多维表格 %d 条记录", created)
        return created

    def replace_all(self, records: list[dict]) -> int:
        """幂等写入：先清空再写。"""
        self.ensure_fields(NEWS_FIELD_SCHEMA)
        self.clear_all_records()
        return self.batch_create(records)


# 初筛结果表的列定义（飞书字段类型：1 多行文本，2 数字，15 超链接）。
# 已有同名列时不会改动，请保证类型一致（尤其「评分」须为数字列）。
NEWS_FIELD_SCHEMA = {
    "标题": 1,
    "链接": 15,
    "来源": 1,
    "摘要": 1,
    "相关性理由": 1,
    "评分": 2,
    "发布时间": 1,
    "标签": 1,
}


def _as_number(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def news_items_to_records(items: list[dict]) -> list[dict]:
    """把初筛后的新闻条目转成多维表格记录。字段名需与你表格列名一致，按需调整。"""
    records = []
    for it in items:
        records.append(
            {
                "fields": {
                    "标题": it.get("title", ""),
                    "链接": {"link": it.get("url", ""), "text": it.get("url", "")}
                    if it.get("url")
                    else "",
                    "来源": it.get("source", ""),
                    "摘要": it.get("summary", ""),
                    "相关性理由": it.get("reason", ""),
                    "评分": _as_number(it.get("score", 0)),  # 模型偶尔返回 "8" 这样的字符串
                    "发布时间": it.get("published", ""),
                    "标签": ", ".join(it.get("tags", []) or []),
                }
            }
        )
    return records
