"""飞书文档（docx）API 封装 —— 用于写日报 / KOL 摘要 / 双周报。

把 Markdown 风格的报告拆成 docx 块写入文档。默认**插到文档最前面**，
最新一期在顶部、往期依次向下，并以分割线隔开。
覆盖标题、正文、无序/有序列表、分割线与 **加粗**，足以承载日报；更复杂排版可按需扩展。
"""
from __future__ import annotations

import re

import requests

import config
from feishu_auth import api_host, auth_headers, extract_doc_id
from logging_utils import get_logger

log = get_logger("feishu.docx")

# 飞书单次创建子块上限为 50
_BATCH = 50


class FeishuDoc:
    def __init__(self, url: str | None = None):
        self.url = url or config.FEISHU_DAILY_REPORT_URL
        self.document_id = extract_doc_id(self.url)
        self._base = f"{api_host()}/open-apis/docx/v1/documents/{self.document_id}"

    def _root_block_id(self) -> str:
        # docx 文档的根 block_id 即 document_id
        return self.document_id

    def insert_blocks(self, blocks: list[dict], at_top: bool = True) -> int:
        """写入块。at_top=True 插到文档开头（保持原有顺序），否则追加到末尾。"""
        parent = self._root_block_id()
        created = 0
        for i in range(0, len(blocks), _BATCH):
            batch = blocks[i : i + _BATCH]
            resp = requests.post(
                f"{self._base}/blocks/{parent}/children",
                headers=auth_headers(),
                json={"children": batch, "index": created if at_top else -1},
                timeout=config.FETCH_TIMEOUT,
            )
            data = resp.json()
            if data.get("code") != 0:
                raise RuntimeError(f"写入文档块失败: {data}")
            created += len(batch)
        log.info("已向文档写入 %d 个块", created)
        return created

    def append_markdown(self, markdown: str, at_top: bool = True) -> int:
        blocks = markdown_to_blocks(markdown)
        # 与上一期之间用分割线隔开
        if at_top:
            blocks.append(_DIVIDER)
        else:
            blocks.insert(0, _DIVIDER)
        return self.insert_blocks(blocks, at_top=at_top)


# ---- Markdown → docx blocks ----------------------------------------------
# block_type：2 正文，3/4/5 一/二/三级标题，12 无序列表，13 有序列表，22 分割线
_KEYS = {2: "text", 3: "heading1", 4: "heading2", 5: "heading3", 12: "bullet", 13: "ordered"}
_DIVIDER = {"block_type": 22, "divider": {}}
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ORDERED = re.compile(r"^\d+[.)]\s+")


def _elements(content: str) -> list[dict]:
    """把 **加粗** 拆成带样式的 text_run，其余为普通文本。"""
    elements = []
    pos = 0
    for m in _BOLD.finditer(content):
        if m.start() > pos:
            elements.append({"text_run": {"content": content[pos : m.start()]}})
        elements.append({"text_run": {"content": m.group(1), "text_element_style": {"bold": True}}})
        pos = m.end()
    if pos < len(content):
        elements.append({"text_run": {"content": content[pos:]}})
    return elements or [{"text_run": {"content": content}}]


def _block(content: str, block_type: int = 2) -> dict:
    return {"block_type": block_type, _KEYS[block_type]: {"elements": _elements(content)}}


def markdown_to_blocks(markdown: str) -> list[dict]:
    blocks: list[dict] = []
    for raw in markdown.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line in ("---", "***"):
            blocks.append(_DIVIDER)
        elif line.startswith("### ") or line.startswith("#### "):
            blocks.append(_block(line.lstrip("#").strip(), 5))
        elif line.startswith("## "):
            blocks.append(_block(line[3:], 4))
        elif line.startswith("# "):
            blocks.append(_block(line[2:], 3))
        elif line.startswith(("- ", "* ", "• ")):
            blocks.append(_block(line[2:], 12))
        elif _ORDERED.match(line):
            blocks.append(_block(_ORDERED.sub("", line, count=1), 13))
        elif line.startswith("> "):
            # 引用块在 docx API 中需要容器块，这里按正文写入
            blocks.append(_block(line[2:], 2))
        else:
            blocks.append(_block(line, 2))
    return blocks
