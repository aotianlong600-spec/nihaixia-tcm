# 工作约定（倪氏经方 · AI 辩证论治与中医大脑重构版）

本仓库为融合「中医学习大脑」5 阶段全量数据与「倪师角色」纯 Python AI 辩证开方工作台的本地优先应用。

## 目录与数据边界

- **不可变预置知识库**：`brain_data/`、`sources/`、`books/` 存放全量 5 阶段经典图谱与 17 册藏书原件。任何运行时请求与测试不得就地改写 `brain_data/`。
- **本机私有运行目录**：`data/` 为 `.gitignore` 忽略的运行数据目录（含 `knowledge.sqlite3`、`clinical.sqlite3`、`consult_history.sqlite3`、`write_token.txt`、`ai_settings.json`、`originals/` 等）。不得清空、覆写用户现有 `data/`，也绝不将任何密钥或本机病历提交到版本库。
- **本地知识写入接口**：`/api/documents/*`、`/api/import/*`、`/api/evidence` 的写入全部经 `app/ingest.py` 走 `X-Write-Token` 校验与事务控制。
- **AI 接口与安全**：
  - `ai/config_store.py` 仅向前端回传脱敏密钥（`api_key_masked`），禁止在接口、日志或测试输出中打印明文 API Key。
  - `/api/ai/*` 的 `POST` 路由在 `app/main.py` 内强制执行同源（`Origin`/`Referer` vs `Host`）校验。
  - 所有 AI 输出必须保留安全熔断与溯源边界：急危重症状（`emergency_triage`）优先警示急救；附子/乌头等峻猛药物及服后麻木昏沉反应必须明确警示停药就医，禁止美化为“瞑眩反应”；绝不捏造页码或无据现代克数。

## 验证

- 任何代码改动后运行：
  ```powershell
  python -m pytest -q
  ```
- 保证测试零失败、零跳过，且不破坏原有 `X-Write-Token` 与 405/401/403 安全契约。
