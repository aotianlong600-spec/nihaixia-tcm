# 只读接口

服务默认监听 `127.0.0.1:8767`。所有接口只接受 GET/HEAD，其余方法返回 405。响应头带 `X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY`、`Cache-Control: no-store`。交互式文档在 `/api/docs`。

## 服务状态

`GET /api/status` → `{"status":"ok","app_id":"tcm-knowledge-core","version":"1.0.0","read_only":true}`

`GET /api/overview` → 文档数、总页数、来源数、方剂数、证型规则数与索引的来源元数据。

## 方剂索引

`GET /api/formulas?q=&limit=` → `{"total":314,"items":[{"id","name","syndrome","six_meridian","source_refs"}]}`

`q` 匹配方名、证型描述与组成药名；`limit` 默认 50，最大 500。

`GET /api/formulas/{formula_id}` → 单方完整条目（含 `components`）。不存在返回 404。

## 原文库

`GET /api/documents` → 已注册原件：`id`（sha256）、`title`、`physical_pages`、`reviewed_pages`、`status`（`pending`/`partial`/`verified`）、`author_status`、`warning`。

`GET /api/documents/{document_id}/pages/{physical_page}` → 单页：`raw_text`、`corrected_text`、`review_status`、`printed_page`、`warning`、`extraction_method`。

`GET /api/documents/{document_id}/pages/{physical_page}/image` → PNG，按版面渲染。页不存在 404，id 非法 400。

`GET /api/sources` → 统一来源目录，PDF 与 DOC/TXT 都列出：`id`、`title`、`format`、`units`、`pdf_pages`、`corpus_role`、`has_ocr`、`warning`。

`GET /api/sources/{source_id}/units/{unit_no}` → 单单元正文与定位：`locator`、`raw_text`、`original_text`、`ocr_text`、`review_status`、`image_url` 或 `original_url`、`warning`。不存在 404。

`GET /api/search?q=&document_id=&limit=` → 跨来源检索命中：`source_id`、`unit_no`、`snippet`、`locator`、`corpus_role`、`warning`。`q` 必填（1–200 字符），`limit` 默认 20，最大 50。

## 错误

| 状态 | 含义 |
|---|---|
| 400 | 参数或库内数据不合法（如 sha256 格式、页号越界） |
| 404 | 目标不存在 |
| 405 | 非 GET 请求 |
| 422 | 查询参数校验失败 |
| 503 | `data/` 目录不可读 |
