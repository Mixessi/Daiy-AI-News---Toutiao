"""飞书文档（docx）API 封装 —— 用于写日报 / KOL 摘要 / 双周报。

以「向文档追加块」的方式写入：把 Markdown 风格的日报按段落/标题拆成 docx 块。
飞书 docx 的块结构较复杂，这里覆盖最常用的标题(heading)与正文(text)块，
足以承载日报内容；更复杂的排版可按需扩展。
"""
from __future__ import annotations

import requests

import config
from feishu_auth import api_host, auth_headers, extract_doc_id
from logging_utils import get_logger

log = get_logger("feishu.docx")


class FeishuDoc:
    def __init__(self, url: str | None = None):
        self.url = url or config.FEISHU_DAILY_REPORT_URL
        self.document_id = extract_doc_id(self.url)
        self._base = f"{api_host()}/open-apis/docx/v1/documents/{self.document_id}"

    def _root_block_id(self) -> str:
        # docx 文档的根 block_id 即 document_id
        return self.document_id

    def append_blocks(self, blocks: list[dict], parent_block_id: str | None = None) -> int:
        parent = parent_block_id or self._root_block_id()
        created = 0
        # 飞书单次创建块数量有限，分批
        for i in range(0, len(blocks), 50):
            batch = blocks[i : i + 50]
            resp = requests.post(
                f"{self._base}/blocks/{parent}/children",
                headers=auth_headers(),
                json={"children": batch, "index": -1},
                timeout=config.FETCH_TIMEOUT,
            )
            data = resp.json()
            if data.get("code") != 0:
                raise RuntimeError(f"追加文档块失败: {data}")
            created += len(batch)
        log.info("已向日报文档追加 %d 个块", created)
        return created

    def append_markdown(self, markdown: str) -> int:
        return self.append_blocks(markdown_to_blocks(markdown))


# ---- Markdown → docx blocks（覆盖标题与正文）------------------------------
def _text_block(content: str, block_type: int = 2) -> dict:
    """block_type: 2=正文文本，3/4/5=一/二/三级标题。"""
    key = {2: "text", 3: "heading1", 4: "heading2", 5: "heading3"}[block_type]
    return {
        "block_type": block_type,
        key: {"elements": [{"text_run": {"content": content}}]},
    }


def markdown_to_blocks(markdown: str) -> list[dict]:
    blocks: list[dict] = []
    for raw in markdown.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.startswith("### "):
            blocks.append(_text_block(line[4:], 5))
        elif line.startswith("## "):
            blocks.append(_text_block(line[3:], 4))
        elif line.startswith("# "):
            blocks.append(_text_block(line[2:], 3))
        elif line.startswith(("- ", "* ")):
            blocks.append(_text_block("• " + line[2:], 2))
        else:
            blocks.append(_text_block(line, 2))
    return blocks
