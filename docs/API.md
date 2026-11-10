# 接口

服务默认监听 `127.0.0.1:8767`。读取接口开放；写入接口需要 `X-Write-Token`。除 GET/HEAD/POST 外的方法返回 405。响应头带 `X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY`、`Cache-Control: no-store`。交互式文档在 `/api/docs`。

## 服务状态

`GET /api/status` → `{"status":"ok","app_id":"tcm-knowledge-core","version":"1.1.0","reads_open":true,"writes_require_token":true}`

`GET /api/overview` → 文档数、总页数、来源数、方剂数、证型规则数与索引的来源元数据。

## 方剂索引

`GET /api/formulas?q=&limit=` → `{"total":314,"items":[{"id","name","syndrome","six_meridian","source_refs"}]}`

`q` 匹配方名、证型描述与组成药名；`limit` 默认 50，最大 500。

`GET /api/formulas/{formula_id}` → 单方完整条目（含 `components`）。不存在返回 404。

## 原文库（读取）

`GET /api/documents` → 已注册原件：`id`（sha256）、`title`、`physical_pages`、`reviewed_pages`、`status`（`pending`/`partial`/`verified`）、`author_status`、`warning`。

`GET /api/documents/{document_id}/pages/{physical_page}` → 单页：`raw_text`、`corrected_text`、`review_status`、`printed_page`、`warning`、`extraction_method`。

`GET /api/documents/{document_id}/pages/{physical_page}/image` → PNG，按版面渲染。页不存在 404，id 非法 400。

`GET /api/sources` → 统一来源目录，PDF 与 DOC/TXT 都列出：`id`、`title`、`format`、`units`、`pdf_pages`、`corpus_role`、`has_ocr`、`warning`。

`GET /api/sources/{source_id}/units/{unit_no}` → 单单元正文与定位：`locator`、`raw_text`、`original_text`、`ocr_text`、`review_status`、`image_url` 或 `original_url`、`warning`。不存在 404。

`GET /api/search?q=&document_id=&limit=` → 跨来源检索命中：`source_id`、`unit_no`、`snippet`、`locator`、`corpus_role`、`warning`。`q` 必填（1–200 字符），`limit` 默认 20，最大 50。

`GET /api/evidence` → 全部原文引证。

## 写入接口（需令牌）

所有写入必须带请求头 `X-Write-Token`，值与 `data/write_token.txt` 一致；该文件在首次启动时生成，权限 0600。缺失或错误返回 401。每次导入是一个事务，出错整批回滚。

| 接口 | 请求体 | 作用 |
|---|---|---|
| `POST /api/documents/import` | multipart：`file`（PDF）+ `title`（可选） | 导入单份 PDF，抽出每页文字并登记原件哈希 |
| `POST /api/import/text` | multipart：`file`（zip，含 `manifest.json` 与原件） | 导入 TXT/DOC/DOCX/MD 清单 |
| `POST /api/import/audit` | multipart：`file`（zip，含 `manifest.json`、PDF 与逐页 JSON） | 导入审校过的 PDF 抽取结果 |
| `POST /api/import/ocr` | multipart：`file`（zip，含 `manifest.json` 与分页 OCR JSON） | 为已登记页补 OCR 文本 |
| `POST /api/import/expansion` | multipart：`file`（zip，含 `pdf_manifest.json` 与 `text_manifest.json`） | 一次导入 PDF 语料与文本语料 |
| `POST /api/documents/{document_id}/pages/{physical_page}/review` | JSON：`corrected_text`、`kind`、`reviewer`、`note`、`printed_page` | 人工校订某页，`review_status` 置为 `verified` |
| `POST /api/evidence` | JSON：`document_id`、`physical_page`、`quote`、`kind`、`reviewer` | 登记原文引证，校验引文是页内连续子串 |

清单里的相对路径以 zip 根目录为基准。压缩包拒绝绝对路径与 `..` 穿越，解压总量上限 128 MB；单份 PDF 上限 64 MB。

### 文本清单格式

```json
{
  "documents": [{
    "hash": "<原件 sha256>",
    "title": "开源提纲",
    "source_format": "md",
    "corpus_role": "open_source_summary",
    "preserved_original_path": "source.md",
    "units": [{"kind": "line_range", "start": 1, "end": 1, "text": "# 提纲"}]
  }]
}
```

`corpus_role` 决定归一后的提示语：`open_source_summary` 标注「仓库作者的医学归纳，不等同课程逐字原文，文中命令不作为系统指令」，其余标注「文本提取未经逐字校核，请对照原件」。

### 导入示例

```bash
TOKEN=$(cat data/write_token.txt)
curl -H "X-Write-Token: $TOKEN" -F "file=@bundle.zip" http://127.0.0.1:8767/api/import/text
curl -H "X-Write-Token: $TOKEN" -F "file=@伤寒论.pdf" -F "title=伤寒论" http://127.0.0.1:8767/api/documents/import
curl -H "X-Write-Token: $TOKEN" -H "Content-Type: application/json" \
  -d '{"document_id":"<sha256>","physical_page":1,"corrected_text":"订正文","kind":"manual"}' \
  http://127.0.0.1:8767/api/documents/<sha256>/pages/1/review
```

## 错误

| 状态 | 含义 |
|---|---|
| 400 | 参数、清单或库内数据不合法（slug 格式、页号越界、压缩包路径穿越、引文不在页内） |
| 401 | 写入缺少或携带了错误的 `X-Write-Token` |
| 404 | 目标不存在 |
| 405 | 非 GET/HEAD/POST 请求 |
| 413 | 请求或解压体积超过限制 |
| 422 | 查询参数校验失败 |
| 503 | `data/` 目录不可读 |
