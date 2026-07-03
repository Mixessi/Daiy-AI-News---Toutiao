# Daily AI News — 追踪体系

一套**无人值守的 AI 资讯监测流水线**，跑在 GitHub Actions 上。每天定时：

1. 从科技媒体 RSS + 微信公众号（via Wechat2RSS）+ Substack 抓取最近 24h 文章
2. 用火山方舟 ARK **豆包**模型做相关性初筛（只留 AI / 短视频 / 网文 / 短剧等战略相关内容，面向今日头条、番茄小说、红果短剧等产品视角）
3. 再用豆包做深度分析、生成日报
4. 结果写入**飞书多维表格 + 飞书日报文档**，并归档到 `daily_filtered/YYYY-MM-DD.json`

> 本仓库按《ByteDance-AI-News 交接与复现指南》的**路径2（按规格从零重建）**实现——原仓库已 404，源码不可得。所有凭证使用你**自己的**火山方舟账户、飞书自建应用与飞书表/文档，通过 GitHub Secrets 注入，代码里不含任何明文 key。

---

## 目录结构

```
rss_filter.py          主入口：抓 RSS + 24h 过滤 + 豆包初筛 + 写飞书多维表格（幂等）
news_analyzer.py       深度分析 + 写飞书日报（--model 可换模型，--feishu 才写飞书）
archive_daily.py       归档当天结果到 daily_filtered/
kol_digest.py          workflow 入口：Twitter KOL 摘要
biweekly_analyzer.py   workflow 入口：双周深度报告

feed_fetcher.py        统一抓取 + 24h 窗口过滤 + 去重
wechat2rss_sync.py     微信公众号源自动同步（打印「自动同步成功,共 N 个公众号」）
doubao_client.py       火山 ARK（OpenAI 兼容）客户端 + 欠费显式告警
feishu_auth.py         飞书鉴权 + URL 解析
feishu_bitable.py      飞书多维表格 API（clear→重写，保证幂等）
feishu_integration.py  飞书文档 API（Markdown → docx 块）
podcast_processor.py   播客 + 火山 ASR 转录（缺 key 自动跳过）
twitter_fetcher.py     Twitter 抓取 via SocialData（缺 key 自动跳过）
twitter_opinions.py    Twitter 舆情增强
config.py              集中式配置（全部从环境变量读取）
logging_utils.py       统一日志 + 欠费/异常醒目告警

data/                  数据源清单（可自由增删）
  rss_feeds.json         科技/AI 媒体 RSS
  substack_feeds.json    Substack newsletter
  wechat_accounts.json   微信公众号对照表
  twitter_kol.json       Twitter KOL 名单
daily_filtered/        每日初筛结果快照（由 workflow commit 回仓库）
.github/workflows/     3 个定时任务
```

## 定时任务

| Workflow | 文件 | Cron (UTC) → 北京时间 | 职责 |
|---|---|---|---|
| Daily AI News Analysis | `daily_news.yml` | `48 1 * * *` → 09:48 | 主流水线：初筛→归档→(可选)雷达→深度分析写日报→提交归档 |
| Daily Twitter KOL Digest | `kol_digest.yml` | `30 0 * * *` → 08:30 | 抓 KOL 动态生成摘要写飞书 |
| Biweekly AI Report | `biweekly_report.yml` | `0 13 * * 3` → 隔周三 21:00 | 双周深度报告（ISO 周次奇偶做隔周闸门） |

三个都支持 **workflow_dispatch** 手动触发。

---

## 快速上手

### 1. 飞书侧准备（手动做一次）
1. 在 [open.feishu.cn](https://open.feishu.cn/app) 创建**自建应用**，拿 App ID / App Secret。
2. 新建/复制你自己的：多维表格（初筛结果）、日报文档、（可选）知识库表、KOL 文档、双周报文档。
3. 给应用开通对应表/文档的**编辑权限**，并开启 `bitable`、`docx`、`wiki` 相关 scope。
4. 多维表格建议包含列：`标题 / 链接 / 来源 / 摘要 / 相关性理由 / 评分 / 发布时间 / 标签`（列名与 `feishu_bitable.news_items_to_records` 对应，可按需改）。

### 2. 火山方舟准备
- 火山控制台 → 火山方舟 → 开通豆包模型、创建 **API Key**。
- ⚠️ **务必充值并设置余额告警/自动续费**——账户欠费会导致流水线静默降级（历史事故根因，见下）。

### 3. 配置 GitHub Secrets
`Settings → Secrets and variables → Actions`，按下表配置（★=主流水线最小必需）：

| Secret | 必需 | 说明 |
|---|---|---|
| `VOLC_API_KEY` | ★ | 火山方舟 API Key |
| `VOLC_ENDPOINT` | 否 | 默认 `https://ark.cn-beijing.volces.com/api/v3` |
| `FEISHU_APP_ID` | ★ | 飞书自建应用 App ID |
| `FEISHU_APP_SECRET` | ★ | 飞书自建应用 App Secret |
| `FEISHU_BITABLE_URL` | ★ | 初筛结果多维表格 URL |
| `FEISHU_KNOWLEDGE_BASE_URL` | 深度分析 | 战略判断知识库表格 URL |
| `FEISHU_DAILY_REPORT_URL` | 深度分析 | 每日报告文档 URL |
| `FEISHU_KOL_DIGEST_URL` | KOL | KOL 摘要文档 URL |
| `FEISHU_BIWEEKLY_REPORT_URL` | 双周 | 双周报文档 URL |
| `WECHAT2RSS_BASE_URL` / `WECHAT2RSS_TOKEN` | 公众号 | 你的 Wechat2RSS 部署地址/令牌 |
| `VOLC_ASR_APPID` / `VOLC_ASR_TOKEN` / `VOLC_ASR_RESOURCE_ID` | 播客 | 火山录音文件识别；不配则跳过 |
| `SOCIALDATA_API_KEY` | Twitter | socialdata.tools；不配则跳过 |
| `AI_NEWS_RADAR_DEPLOY_KEY` / `AI_TO_C_MODEL` | 雷达 | Pages 前端发布；不配则跳过 |

### 4. 本地安全试跑（不写飞书）
```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # 填入你自己的 key，别提交

export DISABLE_FEISHU_WRITE=1 # 只产出本地 JSON
python rss_filter.py          # → filtered_news.json
python news_analyzer.py       # → analysis_output.json
```
去掉 `DISABLE_FEISHU_WRITE` 并加 `--feishu` 即可验证写飞书：
```bash
python news_analyzer.py --feishu
```

### 5. 上线
在 Actions 里手动 **Run** 三个 workflow 各一次，全绿即交付。

---

## 设计要点 / 运维须知

- **火山 ARK OpenAI 兼容**：默认 endpoint `https://ark.cn-beijing.volces.com/api/v3`。
- **初筛/深度分析 Prompt** 分别内联在 `rss_filter.py` / `news_analyzer.py`，便于直接编辑。
- **幂等写飞书**：多维表格写前先 clear 再重写。
- **`DISABLE_FEISHU_WRITE=1`**：只产出本地 JSON、不写飞书，用于安全试跑。
- **增强模块缺 key 自动跳过不报错**：播客 ASR、Twitter 舆情、雷达前端。
- **⚠️ 欠费显式告警（重要）**：大模型调用失败会容错，但检测到 `403 / AccountOverdueError`（火山欠费）时**立即中止、非零退出、workflow 标红**，并打印醒目横幅。原系统曾因欠费**静默降级**——workflow 显示 success，但当天只抓到 20 来条（正常 150~220）。本实现用两道防线杜绝重演：
  1. `doubao_client` 识别欠费 → 抛 `AccountOverdueError` → 主脚本非零退出；
  2. `rss_filter.health_check` 产出低于地板值（默认 40）时醒目告警 + `::error::` 标红。
- **健康区间**：正常一天运行 1 小时+、产出 150~220 条；远低于此视为异常。

### 排查命令
```bash
# 查看某次运行日志里的欠费告警
gh run view <run-id> --log | grep -i overdue

# 确认当天归档条数在正常区间
python - <<'PY'
import json, glob
p = sorted(glob.glob("daily_filtered/*.json"))[-1]
print(p, json.load(open(p))["count"])
PY
```

## 成本参考
主流水线每天约几百次豆包调用，日成本小几块钱；播客 ASR、SocialData 为额外计费项。**真正的风险不是花费而是账户欠费静默停跑，余额告警必设。**
