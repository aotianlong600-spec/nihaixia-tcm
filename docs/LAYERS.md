# 分层与本次重构

## 结论

仓库从「诊疗工作台」收敛为「知识库底座」。算法层与应用层整体移除，保留原文库、方剂索引、检索与只读接口。

保留后的 `app/` 共 5 个模块 1019 行：`knowledge`（427）、`library`（402）、`main`（179）、`domain`（10）、`__init__`（1）。

## 三层边界

| 层 | 内容 | 本次处理 |
|---|---|---|
| 数据层 | `knowledge`（原文、物理页、校订、证据）、`library`（来源目录、单元、检索）、`domain`（领域异常）、`app/resources/` 索引与来源说明 | 保留 |
| 算法层 | `engine`、`formula_engine`、`decision`、`decision_support`、`library_analysis`、`library_evidence`、`library_modifications`、`library_signs`、`consultation_core`、`consultation_library` | 删除（约 2252 行） |
| 应用层 | `main` 完整工作台、`browser_*`、`mobile_*`、`personal`、`research`、`storage`、`backup`、`access`、`lan`、`secrets`、`model*`、`offline_pack`、`offline_runtime`、`portable_validation` | 删除并重写为只读接口（约 4400 行）；`main` 由 610 行降为 179 行 |
| 外围服务 | `ai-bridge/`（模型桥）、`relay/`（模型转发 Worker） | 删除 |
| 证据数据 | `library_evidence/` 4 组 JSON + manifest（组成版本、原文引文、加减原句、体征词） | 按决定删除 |

## 删除理由（用户确认）

1. 范围失控：算法、网页、安卓、模型桥、转发服务塞在一个仓库，维护不动。
2. 算法结果不可靠：方证匹配与加减输出经不起核对，不能作为临床参考，因此不作为"要修好的部分"保留，而是整体移出仓库。
3. 数据来源与标注不合规：删掉算法中间产物后，只剩可溯源的原文与索引，标注责任更清楚。
4. 工程健康度差：测试与依赖跟随算法层一起膨胀，现在只保留数据层用例。

## 保留决定

- `library_evidence/` 删除：它是算法输入，不是可独立消费的原文。
- `frontend/`、`android/` 原样保留：用户决定不动它们。代价是网页端调用的写接口已消失，页面只剩静态壳；安卓构建脚本依赖已删除的知识包导出脚本，当前不可构建。两者都在 README 的遗留目录表里标明。
- 方剂索引保留：它是本仓库对外提供的主要数据资产（314 首方 / 315 条证型规则）。

## 依赖变化

从 8 个包降到 6 个：`fastapi`、`uvicorn`、`pydantic`、`pdfplumber`、`pypdfium2`、`fastjsonschema`。移除 `cryptography`（局域网 TLS）、`python-multipart`（上传接口）。
