# 数据架构与存储边界

本系统采用「预置经典图谱 + 本机私有库 + 本机 AI 配置」三层隔离设计：

## 1. 预置经典知识库（`brain_data/`、`sources/`、`books/`）

从「中医学习大脑 (`tcm-study-brain-v2`)」完整迁入，随源码维护，仅供只读检索与辨证匹配：

- **四大核心经典模块（第 1–4 阶段）**：
  - 人纪针灸：14 经络、穴位、刺灸法则、治症专题及后附索引。
  - 神农本草：385 味（357 正经 + 28 增补）与 38 组跨家对照。
  - 黄帝内经：《素问》74 篇校勘本、专题解析及原书扫描页锚点。
  - 伤寒与金匮经方：299+ 首方剂、原典汉制剂量、炮制说明、古今煎服法与六经归属。
- **第 5 阶段综合图谱与全藏书阁**：
  - 31 大跨书证候群与网络关联边。
  - 汉唐百方（91 方）、督脉压痛诊察、西医介入史提示与临床红线。
  - 17 册藏书全文检索库（人纪四大经典、汉唐经验方、古籍辅注与各家全书），支持逐页上下文定位与原页校验。

## 2. 本机私有库（`data/knowledge.sqlite3` 与 `data/originals/`）

- 通过带 `X-Write-Token` 的写入接口导入用户自己的 PDF、TXT/MD/DOCX 与 OCR 审校结果，计算文件 `sha256` 并保留物理页、印刷页与人工校订记录（`verified`）。
- 用户点击 AI 辩证提问时，`ai/ni_consult.py` 会将预置 17 册藏书检索结果与本机 `sqlite3` 导入原文一并纳入可点击 `[ref:N]` 实证列表，同时标记 `source_scope` 以清晰区分出处。

## 3. 本机 AI 配置与问诊人独立历史（`data/ai_settings.json`、`data/consult_history.sqlite3`）

- `data/ai_settings.json`：保存服务商、协议、Base URL、模型名、倪师人格风格及可选 API Key（文件权限 0600，绝不提交至 Git）。
- 读取配置接口 `GET /api/ai/config` 仅返回 `has_api_key`、`key_source` 与 `api_key_masked`（如 `sk-1...abcd`），绝不在前端或日志暴露明文凭证。
- `data/consult_history.sqlite3`（由 `app/consult_history.py` 管理）：按 `patients`（问诊人）与 `consult_sessions`（外键 `ON DELETE CASCADE`）隔离存储每位问诊人的四诊录入、多轮对话与处方上下文；与既有 `data/clinical.sqlite3` 完全物理隔离，互不覆盖。
