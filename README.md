# 经方原文库 · 数据底座

本仓库是一个**只读的知识库底座**：原文库、开源方剂索引、检索与溯源读取接口。

它不是诊疗应用，也不做辨证。**算法层与应用层已移除**，重构依据见 [docs/LAYERS.md](docs/LAYERS.md)。

## 本仓库包含

| 路径 | 内容 |
|---|---|
| `app/knowledge.py` | 原文库：PDF 导入、物理页与印刷页、文字检索、页面渲染、人工校订与证据表 |
| `app/library.py` | 统一来源目录：来源清单、单元读取、跨来源检索 |
| `app/main.py` | 只读 FastAPI 接口，仅 GET |
| `app/domain.py` | 传输无关的领域异常 |
| `app/resources/open_formula_library.json` | 开源方剂索引：**314 首方、315 条证型规则** |
| `app/resources/来源说明.md` | 索引的来源与授权说明 |
| `tests/` | 数据层与接口测试（51 个用例） |

## 本仓库不包含

- 方证匹配、症状聚类、经方加减推演等**算法层**
- 问诊单、病例、就诊记录、会话等**应用层数据与接口**
- 云端模型接入、OAuth、模型转发服务（原 `ai-bridge/`、`relay/`）
- 知识包打包与导出工具（知识包改为外部 release 资源）

## 快速开始

1. 安装 Python 3.11，双击 `setup.cmd`（创建 `.venv` 并安装依赖）。
2. 双击 `启动离线网页.cmd`。
3. 打开 <http://127.0.0.1:8767/api/status>，或直接读接口：

```
GET /api/status
GET /api/overview
GET /api/formulas?q=桂枝&limit=20
GET /api/formulas/guizhi_tang
GET /api/sources
GET /api/documents
GET /api/documents/{document_id}/pages/{physical_page}
GET /api/documents/{document_id}/pages/{physical_page}/image
GET /api/sources/{source_id}/units/{unit_no}
GET /api/search?q=发热&limit=20
```

交互式文档在同一服务的 `/api/docs`。全部接口只接受 GET；写请求返回 405。完整说明见 [docs/API.md](docs/API.md)。

## 数据

- 方剂索引随源码分发：`app/resources/open_formula_library.json`，来源标注见 `app/resources/来源说明.md`。
- 原文库本体（来源 PDF/DOC/TXT 与物理页）不进入源码树。运行后落在 `data/`，由 `knowledge.sqlite3` 与 `originals/` 组成。
- 同一份原文的原件、字节哈希、物理页与印刷页跨端保持一致；有疑问的页带 `warning`，人工校订后 `review_status` 变为 `verified`。

## 验证

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

`.github/workflows/verify.yml` 在 Windows 上跑同一套用例。

## 遗留目录（本仓库不再维护）

| 路径 | 状态 |
|---|---|
| `frontend/` | 原网页 App。它调用的问诊、决策、模型接口已随算法层删除，页面只剩静态壳，`.github/workflows/web-app.yml` 的发布链路也不再产出可用站点 |
| `android/` | 原离线端。依赖已删除的知识包导出脚本，当前不可构建 |
| `docs/legacy/` | 旧版设计文档：决策 V3、推理工作流、配置档位、OAuth 排错、多端说明等 |

这三处保留原样以便回溯；要用就按新边界重写，而不是就地修补。

## 重构记录

删除算法层与应用层，仓库回到数据底座。逐条清单与判定依据见 [docs/LAYERS.md](docs/LAYERS.md)。
