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

