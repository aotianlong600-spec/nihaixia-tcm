# 接口说明

服务默认监听 `127.0.0.1:8767`。交互式 OpenAPI 文档在 `/api/docs`。除 `GET`/`HEAD`/`POST` 外的方法返回 `405`。响应头固定附带 `X-Content-Type-Options: nosniff`，`/api/*` 响应附带 `Cache-Control: no-store`。

## 1. 服务状态与总览

- `GET /api/status` → `{"status":"ok","app_id":"tcm-knowledge-core","engine":"tcm-study-brain-v2+ni-ai","reads_open":true,"writes_require_token":true,"ai_ready":...}`
- `GET /api/overview` → 经方、本草、针灸、内经、本机文档/来源数及 17 册书库统计。

## 2. 倪师 AI 辩证开方接口（同源保护）

> 所有 `/api/ai/*` 的 `POST` 接口均强制检查 `Origin`/`Referer` 与当前 `Host` 一致，跨源调用返回 `403`。

| 接口 | 方法 | 作用 |
|---|---|---|
| `/api/ai/config` | `GET` | 获取当前脫敏 AI 配置、支持的服务商预设（`deepseek`/`openai`/`gemini`/`anthropic`/`ollama`/`custom`）与 3 档倪师人格说明 |
| `/api/ai/config` | `POST` | 保存模型配置至 `data/ai_settings.json`；未填 `api_key` 时保留原密钥，`clear_api_key=true` 清空密钥 |
| `/api/ai/models` | `POST` | 探测并返回上游模型列表（或 Ollama `/api/tags`），失败回落内置推荐列表或返回清理后的错误 |
| `/api/ai/test` | `POST` | 发送轻量探活请求，测量端到端延迟（`latency_ms`）并返回响应预览 |
| `/api/ai/packet` | `POST` | 传入 `query` / `pulse` / `tongue` / `entity_focus`，返回完整的 5 阶段辨证处方包、安全边界与 `[ref:N]` 实证列表 |
| `/api/ai/chat` | `POST` | 非流式完成一轮辨证开方；`offline=true` 或未配 Key 时返回本地中医大脑实证直出结果 |
| `/api/ai/chat/stream` | `POST` | SSE 流式输出，依次推送 `event: context`（先下发处方包与安全预警）、`event: reasoning`（思考过程）、`event: delta`（正文增量）与 `event: done`（含引用映射）；上游失败时自动发射 `event: error` 并无缝接续本地离线实证兜底 |
| `/api/ai/patients` | `GET` / `POST` | 列出所有问诊人（首次为空时自动初始化默认问诊人），或新增问诊人并自动创建首个独立会话 |
| `/api/ai/patients/{patient_id}/update` | `POST` | 更新指定问诊人的姓名、性别、年龄、体质/病史备注 |
| `/api/ai/patients/{patient_id}/delete` | `POST` | 删除指定问诊人并级联清理其所属全部问诊历史 |
| `/api/ai/patients/{patient_id}/sessions` | `GET` / `POST` | 列出该问诊人的独立历史列表，或「新开」一次独立问诊会话 |
| `/api/ai/sessions/{session_id}` | `GET` | 读取单次历史会话的完整四诊录入、对话轮次与处方包 |
| `/api/ai/sessions/{session_id}/save` | `POST` | 保存更新当前会话标题、四诊录入、挂靠条目、对话轮次与处方上下文 |
| `/api/ai/sessions/{session_id}/delete` | `POST` | 删除单条历史问诊记录（仅影响所属问诊人） |

## 3. 中医大脑第 1–5 阶段与 17 册书库读取接口

- 经方 / 六经 / 本草 / 煎服法：`/api/formulas`、`/api/formulas/{id}`、`/api/formulas/diagnose`、`/api/herbs`、`/api/six-channels`、`/api/jinkui/*`
- 针灸 / 神农本草 / 黄帝内经：`/api/acupuncture/*`、`/api/bencao/*`、`/api/neijing/*`
- 第 5 阶段综合与汉唐：`/api/stage5/overview`、`/api/stage5/compose`、`/api/stage5/ground`、`/api/hantang/*`
- 17 册藏书与原页上下文：`/api/library/books`、`/api/library/locate`、`/api/library/books/{book_id}/pages/{page_no}`、`/api/library/books/{book_id}/context`、`/api/library/search`

## 4. 本地私有导入与校订接口（需 `X-Write-Token`）

令牌保存在 `data/write_token.txt`（缺失或错误返回 `401`）：

- 读取：`/api/documents`、`/api/documents/{id}/pages/{n}`、`/api/documents/{id}/pages/{n}/image`、`/api/sources`、`/api/sources/{id}/units/{n}`、`/api/search`、`/api/evidence`
- 写入：`/api/documents/import`、`/api/import/text`、`/api/import/audit`、`/api/import/ocr`、`/api/import/expansion`、`/api/documents/{id}/pages/{n}/review`、`/api/evidence`
