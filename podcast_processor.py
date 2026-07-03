"""播客增强：抓播客音频 → 火山 ASR 录音文件识别 → 要点。

需要 VOLC_ASR_APPID / VOLC_ASR_TOKEN / VOLC_ASR_RESOURCE_ID，缺任一则整块跳过
（返回空字符串，绝不报错阻断主流水线）。

说明：火山「录音文件识别」是异步任务（提交 → 轮询），此处提供最小可用骨架，
真实音频源与轮询细节按火山语音技术文档接入。默认播客源清单可放 data/podcasts.json。
"""
from __future__ import annotations

import config
from logging_utils import get_logger

log = get_logger("podcast")


def _asr_ready() -> bool:
    return bool(config.VOLC_ASR_APPID and config.VOLC_ASR_TOKEN and config.VOLC_ASR_RESOURCE_ID)


def get_podcast_highlights() -> str:
    """返回播客要点文本；未配置 ASR 或无源时返回空串（调用方据此跳过）。"""
    if not _asr_ready():
        log.info("未配置火山 ASR（VOLC_ASR_*），跳过播客增强。")
        return ""

    podcasts = _load_podcast_sources()
    if not podcasts:
        log.info("无播客源（data/podcasts.json 未配置），跳过。")
        return ""

    highlights = []
    for p in podcasts:
        try:
            text = _transcribe(p["audio_url"])
            if text:
                highlights.append(f"《{p.get('name','播客')}》：{text[:500]}")
        except Exception as exc:  # 单个失败不影响整体
            log.warning("播客 %s 处理失败：%s", p.get("name"), exc)
    return "\n".join(highlights)


def _load_podcast_sources() -> list[dict]:
    import json

    path = config.DATA_DIR / "podcasts.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("podcasts", [])
    except Exception:
        return []


def _transcribe(audio_url: str) -> str:
    """提交火山录音文件识别任务并等待结果（最小骨架）。"""
    import time

    import requests

    submit = requests.post(
        "https://openspeech.bytedance.com/api/v1/auc/submit",
        headers={
            "Authorization": f"Bearer;{config.VOLC_ASR_TOKEN}",
            "Content-Type": "application/json",
        },
        json={
            "app": {"appid": config.VOLC_ASR_APPID, "token": config.VOLC_ASR_TOKEN,
                    "cluster": config.VOLC_ASR_RESOURCE_ID},
            "user": {"uid": "ai-news"},
            "audio": {"url": audio_url, "format": "mp3"},
            "request": {"nbest": 1},
        },
        timeout=config.FETCH_TIMEOUT,
    )
    task_id = submit.json().get("resp", {}).get("id")
    if not task_id:
        return ""
    for _ in range(30):  # 轮询上限
        time.sleep(10)
        q = requests.get(
            "https://openspeech.bytedance.com/api/v1/auc/query",
            params={"appid": config.VOLC_ASR_APPID, "token": config.VOLC_ASR_TOKEN, "id": task_id},
            timeout=config.FETCH_TIMEOUT,
        ).json()
        resp = q.get("resp", {})
        if resp.get("code") == 1000:  # 完成
            utterances = resp.get("utterances") or []
            return " ".join(u.get("text", "") for u in utterances)
    return ""
