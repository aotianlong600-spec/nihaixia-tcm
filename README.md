# 倪氏经方 · AI 辩证论治与中医学习大脑

基于「中医学习大脑 (`tcm-study-brain-v2`)」重构升级的 **AI 辩证开方与经方经典学习系统**：输入症状、脉象、舌象，实时流式输出「倪师角色」辨证思路与完整经方/合方处方，并逐条对照 5 阶段知识图谱与 17 册原典书库。

> ⚠️ **安全与研习声明**：本系统输出的辨证思路、经方组成、汉制原量、煎服法与配穴仅用于经典学习与临床辅助梳理，不替代执业医师线下面诊与急救。遇急危重症或含附子、乌头、半夏、巴豆等峻猛药味时，系统会触发安全预警，抓取药材与服药前务必面诊核对炮制规范与剂量。

## 核心能力

| 模块 | 说明 |
|---|---|
| **倪师 AI 开方工作台** | 默认首页三栏工作台：左侧「问诊人 & 独立历史」管理（支持增删改问诊人与多轮「新开」/删除历史）；中间分类四诊采集盘（常见症状/舌诊/脉诊/腹诊/眼·指诊/压痛点(倪师)/否定排除/病历补充）+ 倪师流式 SSE 辩证开方；右侧多页签实证处方侧栏（`主力方 · 合方` 含匹配度与味数/`配穴 · 汉唐`/`原典 [ref]`） |
| **纯 Python 大模型直连** | 彻底移除脆弱 Node `ai-bridge`，采用后端 `httpx` 原生异步流式直连 DeepSeek / OpenAI 兼容网关 / Google Gemini / Anthropic Claude / 本地 Ollama；无 API Key 时自动启用本地中医大脑直出经方，保证随时可用 |
| **优化“倪师角色”** | 融合人纪课堂带教神韵与汉唐临床推演逻辑：先抓六经表里寒热、明快设喻定方，同时严守急症转诊红线、剧毒药不良反应警惕（绝不将麻木昏沉曲解为“瞑眩反应”）与零编造原典引用 |
| **第 1–4 阶段四大典籍** | 针灸（十四经穴位/治症/法则）、神农本草（385 味对照）、黄帝内经《素问》（74 篇/专题）、伤寒/金匮经方（299+ 首含同名异方、六经辨证、古今煎服对照） |
| **第 5 阶段综合与 17 册藏书阁** | 31 组跨书证候图谱、动态合方配穴引擎、汉唐百方（91 方）、17 册全文检索与影印页码对照 |
| **本地私有导入与校订** | 保留 `X-Write-Token` 令牌保护的 SQLite 本地导入与人工校订接口（`/api/documents/*`、`/api/import/*`、`/api/evidence`），并参与 AI 引用检索 |

## 目录结构

| 路径 | 角色 |
|---|---|
| `ai/` | 纯 Python 倪师 AI 引擎（`config_store.py`、`llm_client.py`、`ni_persona.py`、`ni_consult.py`、`grounded_study.py`） |
| `app/` | FastAPI 主服务（`main.py`）、5 阶段检索编排（`catalog.py`、`syndrome_composer.py`、`hantang_catalog.py` 等）、独立问诊人历史库（`consult_history.py`）与 SQLite 导入层（`knowledge.py`、`library.py`、`ingest.py`） |
| `brain_data/` | 不可变预置 5 阶段知识数据与 17 册书库索引（从中医大脑完整迁入） |
| `sources/` / `books/` | 经方、本草、内经、针灸、汉唐及古籍对照文本原件 |
| `web/` | 零构建原生前端（`index.html`、`ni_ai.js`、`app.js`、`library_stage5.js`、`style.css` 等） |
| `data/` | 本机运行目录（`.gitignore` 忽略）：保存 `knowledge.sqlite3`、`write_token.txt`、`ai_settings.json` 与本机导入原件，更新源码不会覆盖 |

## 快速开始

1. 确认已安装 Python 3.11+，首次安装依赖：
   ```powershell
   .\setup.cmd
   # 或手工安装
   python -m pip install -r requirements.txt
   ```
2. 启动本地服务（默认监听 `http://127.0.0.1:8767`）：
   ```powershell
   .\启动离线网页.cmd
   # 或命令行启动
   python scripts/run.py
   ```
3. 浏览器打开 <http://127.0.0.1:8767/>：
   - **免 Key 立即可用**：直接在左侧点选病案或输入症状，点「倪师辩证出方」即可由中医大脑直出主方、原方用量与煎服法；
   - **接入大模型（推荐）**：点击右上角「模型设置」，选择 **DeepSeek** / **OpenAI** / **Gemini** / **Anthropic Claude** / **本地 Ollama**，支持「获取模型列表」「测试连通」并将配置原子保存至本地 `data/ai_settings.json`；也可通过环境变量 `DEEPSEEK_API_KEY`、`OPENAI_API_KEY`、`GEMINI_API_KEY`、`ANTHROPIC_API_KEY`、`TCM_AI_API_KEY` 自动读取。

## 验证与校验

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -c "from etl.library.validate import validate_all; print(validate_all())"
```

更多接口明细见 [docs/API.md](docs/API.md)，数据分层说明见 [docs/DATA.md](docs/DATA.md)。
