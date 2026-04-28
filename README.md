# AI Radar

AI Radar 是一个面向 AI 产品 / 技术情报流的多 Agent 雷达系统。

它想解决的核心问题很直接：

- 一个新热点到底是什么
- 它用了什么技术
- 和以前的方法相比改进在哪里
- 可能带来什么新的产品方向
- 为什么它和已有知识有关，值得继续了解

当前项目已经能跑通这条主链：

- 多源抓取：`arXiv / Product Hunt / Reddit / Notion`
- 新颖度判断：`Novelty Scorer`
- 双池推荐：`精准池 / 探索池`
- 对话深聊：`Chat Agent + SSE`
- 记忆沉淀：`Memory Agent + Notion wiki/raw/preferences`
- 轻量偏好进化：最近 7 天 `open / save / skip` 行为反馈到次日规划
- 第一批评测脚本：`Novelty / Intent / Wiki Quality / Recommendation Precision@K`

当前全量测试结果：`58 passed`

## 1. 项目结构

```text
ai_radar/
├── agents/         # Orchestrator / Crawler / Novelty / Recommender / Chat / Memory
├── api/            # FastAPI routes + services
├── data/           # 本地运行态数据（默认不提交）
├── evaluation/     # 评测脚本与模板
├── frontend/       # Vite + React + TypeScript
├── mcp_servers/    # 外部数据源工具
├── runtime/        # mini runtime / llm client / observability
├── schemas/        # 数据契约
├── skills/         # Skill 系统
└── tests/          # 单元与集成测试
```

## 2. 运行前需要准备什么

至少要准备三类配置：

- 一个 OpenAI 兼容的 LLM 接口
- Product Hunt 凭据
- Notion 凭据和页面 / 数据库 ID

### 2.1 LLM

用于：

- 卡片中文总结
- Chat 回答
- 后续部分评测和生成流程

环境变量：

```bash
LLM_API_KEY=your_key_here
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-v4-flash
```

说明：

- 当前项目走的是 OpenAI 兼容接口
- 默认接的是 DeepSeek
- 只要兼容 Chat Completions 风格接口，理论上都可以替换

### 2.2 Product Hunt

用于：

- `search_product_hunt`

环境变量：

```bash
PRODUCTHUNT_API_KEY=your_key_here
PRODUCTHUNT_API_SECRET=your_secret_here
```

说明：

- 如果只有 `PRODUCTHUNT_API_KEY`，项目会把它当 developer token 使用
- 如果同时提供 `PRODUCTHUNT_API_SECRET`，会先走 client credentials 换 access token

### 2.3 Notion

用于：

- wiki 知识库
- raw 原始抓取内容
- preferences 镜像页

环境变量：

```bash
NOTION_API_KEY=your_key_here
NOTION_WIKI_DATABASE_ID=your_wiki_db_id
NOTION_RAW_DATABASE_ID=your_raw_db_id
NOTION_PREFERENCES_PAGE_ID=your_preferences_page_id
```

## 3. Notion 怎么建

### 3.1 wiki Database

当前代码支持较宽松的 schema，但推荐用这套：

| 字段名 | 类型 | 用途 |
|---|---|---|
| `名称` | `title` | 产品 / 技术主体 |
| `摘要` | `rich_text` | 一句话说明 |
| `标签` | `rich_text` 或 `multi_select` | 标签体系 |
| `更新时间` | `date` | 最近更新时间 |

说明：

- 当前代码兼容多种字段别名
- `标签` 同时兼容 `rich_text` 和 `multi_select`

### 3.2 raw Database

推荐字段：

| 字段名 | 类型 | 用途 |
|---|---|---|
| `title` | `title` | 原始内容标题 |
| `source_url` | `url` | 来源链接 |
| `source_platform` | `rich_text` | 来源平台 |
| `fetched_at` | `date` | 抓取时间 |

### 3.3 preferences 页面

当前实现里，`preferences` 不要求建成 Database，更推荐直接用一个普通 Notion 页面。

你只需要：

- 新建一个页面，比如 `preference`
- 把这个页面分享给当前 integration
- 把页面 ID 配到：

```bash
NOTION_PREFERENCES_PAGE_ID=...
```

系统会在这个页面下面自动维护一个子页面：

- `AI Radar Preferences Snapshot`

用于镜像当前本地 `preferences.json`

## 4. 环境变量放在哪里

在项目根目录创建 `.env`：

```bash
LLM_API_KEY=your_key_here
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-v4-flash

NOTION_API_KEY=your_key_here
NOTION_WIKI_DATABASE_ID=your_wiki_db_id
NOTION_RAW_DATABASE_ID=your_raw_db_id
NOTION_PREFERENCES_PAGE_ID=your_preferences_page_id

PRODUCTHUNT_API_KEY=your_key_here
PRODUCTHUNT_API_SECRET=your_secret_here
```

前端本地开发可选创建：

`frontend/.env.local`

```bash
VITE_ENABLE_MOCK_FEED=true
```

说明：

- 有真实后端时建议关闭 mock
- 没有后端时可以打开，只看前端界面

## 5. 本地启动

### 5.1 安装 Python 依赖

```bash
pip install -r requirements.txt
```

### 5.2 启动后端

在项目根目录执行：

```bash
python -m uvicorn ai_radar.api.main:app --host 127.0.0.1 --port 8000
```

启动后可以先看：

- 健康检查：[http://127.0.0.1:8000/healthz](http://127.0.0.1:8000/healthz)
- Swagger：[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

### 5.3 启动前端

```bash
cd frontend
npm install
npm run dev
```

前端默认通过 Vite proxy 把 `/api/*` 转到：

- `http://127.0.0.1:8000`

前端地址：

- [http://127.0.0.1:5173](http://127.0.0.1:5173)

## 6. 启动后先检查什么

建议按这个顺序检查：

1. 后端健康检查  
- `GET /healthz`

2. Feed 接口  
- `GET /api/feed`

3. Preferences 接口  
- `GET /api/preferences`

4. 前端首页  
- 打开 `http://127.0.0.1:5173`

5. Notion 写入链路  
- 前端点一张卡片 `Save`
- 去 Notion `wiki` 看是否有新记录

## 7. 评测脚本

当前已经能直接运行：

```bash
python -m ai_radar.evaluation.intent_eval evaluation/data/intent_ground_truth.json
python -m ai_radar.evaluation.wiki_quality_eval evaluation/data/wiki_quality_samples.json
python -m ai_radar.evaluation.novelty_eval evaluation/data/novelty_ground_truth.json
python -m ai_radar.evaluation.recommendation_eval evaluation/data/recommendation_judgments.json --db-path data/radar.db
```

说明：

- `intent_eval` 和 `wiki_quality_eval` 现在可以直接用模板烟测
- `novelty_eval` 能跑通，但要得到有意义的指标，仍需要真实标注集
- `recommendation_eval` 依赖 SQLite `feed_history` 和人工 relevance 标注

当前评测快照见：

- [evaluation/CURRENT_EVAL_SNAPSHOT.md](./evaluation/CURRENT_EVAL_SNAPSHOT.md)

## 8. 当前局限

### 评测指标需要真实使用数据

评测脚本框架已就绪（见 `evaluation/`），但当前 `evaluation/data/` 下放的是结构示例，
不是真实标注集。各项指标需要积累真实使用数据后才有意义：

- **Novelty Scorer 准确率**：需要手动标注 30+ 条内容的真实新颖度作为 ground truth
- **推荐 Precision@K**：依赖 `feed_history` 表有一定量的真实使用记录
- **意图识别准确率**：需要手动构造 50 条覆盖三类意图的测试 query

### 偏好进化是规则统计版

当前偏好进化基于最近 7 天行为的关键词统计，产出 `boosted_topics / suppressed_topics`。
关键词从卡片标题提取，缺少语义聚类，冷启动阶段（使用不足 7 天）效果有限。

### Filter Bubble 提示未落地到前端

后端 `/api/feed` 已经返回 `filter_bubble_warning` 字段
（连续 5 天探索池全跳过时为 `true`），前端暂未渲染这个字段。

### Dashboard 只有当日快照

Dashboard「情报质量」Tab 展示的是当日数据，没有跨日趋势图。
`feed_history` 和 `user_actions` 表已建好，趋势折线图尚未实现。

### Chat 意图类型未在界面展示

后端 SSE `event: meta` 里已包含 `intent_type`（`exploratory / deep_dive / comparison`），
前端 `ChatPage` 目前没有渲染该字段。

### 信息源覆盖有限

当前接入：arXiv、Product Hunt、Reddit（via YARS）。  
Reddit 抓取依赖非官方库 YARS，存在一定稳定性风险。  
Hacker News、GitHub Releases、36氪、即刻等暂未接入。

### Notion 强依赖

所有知识沉淀写入 Notion，依赖网络可用性和 Notion API 配额（限流 3 req/s）。

---

## 9. Roadmap

### 补全评测数据闭环

脚本已就绪，补充真实标注集后可直接产出指标：
- 手动标注 Novelty ground truth，运行三版本对比（LLM only → + arXiv 核查 → + 互审）
- 积累 `feed_history` 记录后运行 Precision@K
- 构造意图识别测试集，优化 system prompt 并对比提升前后差距

### Filter Bubble 提示 banner

读取 `/api/feed` 返回的 `filter_bubble_warning`，
为 `true` 时在 Feed 顶部展示提示，引导用户关注探索池内容。

### Dashboard 历史趋势图

基于 `user_actions` 按日聚合，绘制点开率 / 跳过率 / 探索池命中率折线图。
`frontend/src/components/SparkLine.tsx` 组件骨架已存在。

### 偏好进化升级

将当前关键词统计升级为语义方向：
- embedding 聚类合并同义关键词
- 或直接用 LLM 读近期行为记录，产出结构化偏好 diff

### 扩展信息源

- Hacker News：官方 API，免认证
- GitHub Releases：官方 API，只需 `GITHUB_TOKEN`
- 36氪 / 即刻：需要爬虫维护

### 部署

- 后端：Railway / Render 部署 Python 服务
- 前端：Vercel import `frontend/` 目录
- 将 `.env` 环境变量迁移到平台 Secrets

