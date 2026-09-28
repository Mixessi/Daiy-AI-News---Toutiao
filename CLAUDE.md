# CLAUDE.md

给未来在本仓库工作的 Claude Code 的说明。本仓库是一套 **AI 资讯监测流水线**，
按《ByteDance-AI-News 交接与复现指南（方式C：完全自有账户）》的**路径2（按规格重建）**
从零实现（原仓库 `RyanLiangwh/AI_News_ByteDance` 已 404，源码不可得）。

## 系统在做什么
GitHub Actions 每天定时：抓 RSS + 微信公众号（Wechat2RSS）+ Substack 近 24h 文章
→ 豆包初筛（战略相关性，面向今日头条/番茄小说/红果短剧）→ 豆包深度分析生成日报
→ 写飞书多维表格 + 飞书日报文档 → 归档 `daily_filtered/YYYY-MM-DD.json` 回仓库。

## 架构与文件（改动前先读）
- 入口脚本：`rss_filter.py`（主）、`news_analyzer.py`（深度分析，`--feishu`/`--model`）、
  `archive_daily.py`、`kol_digest.py`、`biweekly_analyzer.py`。
- 抓取：`feed_fetcher.py`（24h 窗+去重）、`wechat2rss_sync.py`（公众号自动同步）。
- 大模型：`doubao_client.py`（火山 ARK，OpenAI 兼容 `/chat/completions`）。
- 飞书：`feishu_auth.py`（token + URL 解析）、`feishu_bitable.py`（多维表格，幂等，缺列自动建）、
  `feishu_integration.py`（docx，Markdown→块，新一期插顶部）、`feishu_webhook.py`（群机器人，可选）。
- 日报落地：`reports/YYYY-MM-DD.md` + `$GITHUB_STEP_SUMMARY`，不依赖飞书配置。
- 数据源体检：`feed_check.py` / `feed_check.yml`（只抓取，改 `data/` 自动跑）。
- 增强（缺 key 自动跳过）：`podcast_processor.py`、`twitter_fetcher.py`、`twitter_opinions.py`。
- 基建：`config.py`（全部配置从环境变量读）、`logging_utils.py`（告警）。
- 数据源清单：`data/*.json`。Workflow：`.github/workflows/*.yml`。

## 硬性约束（不要违反）
1. **永远不在代码里写真实 key**。凭证只从环境变量读（见 `config.py` / `.env.example`）。
   `.env` 已被 `.gitignore` 忽略。
2. **欠费必须显式告警，禁止静默降级**。历史事故：火山账户欠费时，workflow 仍显示
   success，但当天只抓到 ~20 条（正常 150~220）。已有两道防线，改动相关逻辑时务必保留：
   - `doubao_client._looks_overdue` → 抛 `AccountOverdueError` → 入口脚本非零退出；
   - `rss_filter.health_check` 低于 `ANOMALY_FLOOR` 时醒目横幅 + GitHub `::error::` 标红。
3. **幂等**：写飞书多维表格前先 `clear_all_records` 再 `batch_create`。
4. **容错但告警**：单源/单批失败要跳过并 `warning`，不能让整条流水线崩，但也不能静默。
5. **`DISABLE_FEISHU_WRITE=1`** 必须始终有效（只产出本地 JSON）。

## 模型
- 初筛：`doubao-1-5-pro-32k-250115`（`DOUBAO_FILTER_MODEL`）
- 深度分析：`doubao-seed-1-6-251015`（`DOUBAO_ANALYZE_MODEL`，`news_analyzer.py --model` 可覆盖）
- Endpoint 默认 `https://ark.cn-beijing.volces.com/api/v3`

## Prompt 位置
- 初筛 Prompt：`rss_filter.py` 顶部 `FILTER_SYSTEM_PROMPT`
- 深度分析 Prompt：`news_analyzer.py` 顶部 `ANALYZE_SYSTEM_PROMPT`
直接编辑这两处即可调整口径。

## 本地验证
```bash
python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt
export DISABLE_FEISHU_WRITE=1
python rss_filter.py        # 产出 filtered_news.json，不写飞书
python news_analyzer.py     # 产出 analysis_output.json
```
> 注意：受限网络环境（如本 CI sandbox）会拦截外网抓取，`fetch_recent` 会优雅返回 0 条。
> 逻辑正确性可用注入数据验证（见提交历史里的离线测试）。

## 待接入 / 可扩展
- `data/rss_feeds.json`（~39）、`substack_feeds.json`（~28，`*.substack.com` 子域名在 GH runner 上 403，只用自定义域名）已经 runner 体检；Newsletter 可继续
  扩到指南所述约 55。公众号对照清单约 31 个但 `feed_id` 为空，真实源需通过 `WECHAT2RSS_BASE_URL` 同步。
- 本 sandbox 无法访问外网 feed；验证数据源请推送后看 Feed Health Check 的日志。
- `podcast_processor._transcribe` 与 `twitter_fetcher` 是最小可用骨架，接真实源时按
  火山语音 / SocialData 文档补全。
- AI News Radar 前端发布在 `daily_news.yml` 是占位步骤（`continue-on-error`，缺
  `AI_NEWS_RADAR_DEPLOY_KEY` 自动跳过）。
