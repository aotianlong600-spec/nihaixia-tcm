# 临床辨证辅助引擎 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付 Windows 本地可运行的工程验证版，完成七份资料检索溯源、确定性规则分析、加减风险、医生审核及复诊，并提供可配置模型通道。

**Architecture:** FastAPI 同源提供 API 和 Vue 静态构建；SQLite 保存版本和访次，PDF 留本地。纯函数规则核心与存储/网络分开；Pi Node 子进程仅推理。所有临床输出保持模拟验证状态。

**Tech Stack:** Python 3.11、FastAPI/Pydantic 2、SQLite、pdfplumber/pypdfium2、Vue 3/TypeScript/Element Plus/Vite、Pi AI 1.3.0、pytest。

**Spec:** `C:/Users/longa/Documents/Codex/2026-11-05/skill-https-jangviktor-web-github-io-3/outputs/临床辨证辅助引擎_设计基线.md`（用户2026-11-05已确认）。

## Global Constraints

- Windows 单机单用户；仅监听127.0.0.1；前后端同源、会话与写操作CSRF保护。
- 规则核心无网络和副作用；未知不当否定，冲突不静默解决，历史/未核实事实不当当前输入。
- 原文、订正、校注、归纳与模型解释分层；未审核资料可检索但不得自动发布临床规则。
- 已发布版本不可变；旧分析保留输入/证据/规则快照；访次改动使旧分析过期。
- 没有剂量依据不生成剂量；不同炮制/计量基础不自动合并；安全未知不显示通过。
- 模型外发默认关闭，无静默供应商切换；秘密不进前端、日志、源码和备份。
- 使用合成病例验收；程序运行不代表临床有效；原课程全文不随源码包分发。

## Review Focus

1. 跨时点和矛盾事实：只用当次核实输入，冲突显示待核——任务1、3测试。
2. PDF有文本但乱序/粗体重复：保留未校核标记和原件；不假装自动纠正——任务2测试。
3. 页码存在但引文不匹配：证据片段必须真在已选文本内，发布必须完成审核——任务2、3测试。
4. 模型断流/取消/非法引用：不得写成有效结果——任务4测试。
5. 恢复覆盖或泄密：加密备份排除凭据，恢复只到空目录，重算哈希/数据库完整性——任务5测试。

## 文件和接口边界

工程根：`C:/Users/longa/Documents/Codex/2026-11-05/skill-https-jangviktor-web-github-io-3/tcm-assistant`。

`docs/API.md` 是服务/界面唯一接口契约。各实现者只写所负责文件；协调者负责集成和提交，避免并行操作Git索引。

### Task 1: 确定性规则、计量和加减核心

**Files:** `app/engine.py`、`tests/test_engine.py`。

**Interfaces:** `validate_rule(rule: dict) -> dict`；`analyze(facts: list[dict], rules: list[dict], context: dict | None = None) -> dict`；`apply_modifications(formula: list[dict], modifications: list[dict], facts: list[dict], base_formula_id: str = '') -> dict`；`check_formula(formula: list[dict], context: dict | None = None, safety_rules: list[dict] | None = None) -> dict`。输入字段见API契约。

- [ ] 先写行为测试：未记录有汗为unknown、必要未知不能被支持条件补齐、相关冲突pending、历史/未核事实忽略、排除命中不满足、未发布/撤回规则忽略、危险规则命中不生成方药、恶意表达式拒绝。
- [ ] 运行 `python -m pytest tests/test_engine.py -q`，观察未实现行为失败。
- [ ] 实现受限三值表达式、条件追踪和候选；不发诊断概率。
- [ ] 添加加减冲突、版本不符、不同炮制/计量、Decimal精度、安全库缺失/条件不足测试，观察失败后实现。
- [ ] 上述命令全绿；协调者按本任务文件提交。

### Task 2: 原件、页级检索与证据校核

**Files:** `app/knowledge.py`、`scripts/import_audit.py`、`tests/test_knowledge.py`。

**Interfaces:** `init_knowledge(conn, data_dir)`；`import_pdf(conn, data_dir, source: Path, title: str = '') -> dict`；`import_audit(conn, data_dir, manifest_path: Path) -> dict`；`list_documents(conn) -> list[dict]`；`search(conn, query: str, document_id: str | None = None, limit: int = 30) -> list[dict]`；`get_page(conn, document_id, physical_page) -> dict | None`；`review_page(conn, document_id, physical_page, payload) -> dict`；`create_evidence(conn, payload) -> dict`；`get_evidence(conn, evidence_id) -> dict | None`；`list_evidence(conn) -> list[dict]`；`document_path(conn, data_dir, document_id) -> Path`。

- [ ] 先测试：哈希去重，中文两字短查询/标点不报错，页码越界，引用不存在的文本拒绝，原文/订正分开，PDF路径不可越界；审计导入标pending而非verified。
- [ ] 运行 `python -m pytest tests/test_knowledge.py -q`，观察失败，再建最小SQLite表与索引。
- [ ] 保留逐页原始文本，搜索使用派生索引；已知异常标记，并提供PDF原件地址和物理页链接。
- [ ] 审计导入复用本地1935页文本，校验源文件哈希和页号，不重复跑全库抽取，不外发。
- [ ] 测试全绿；运行实际七份审计导入并核对1935页和重复导入；协调者提交。

### Task 3: 访次、审核、快照与受保护API

**Files:** `app/main.py`、`app/storage.py`、`tests/test_api.py`、`requirements.txt`、`scripts/run.py`。

**Interfaces:** `create_app(data_dir: Path | None = None) -> FastAPI`，同源路由以API契约为准。消费任务1、2接口。

- [ ] 先写API集成测试：无会话拒绝、跨源/缺CSRF写入拒绝、旧revision409、规则审核前不能发布、发布后不可改写、输入变化旧分析stale、决定/分析分存、复诊不自动带入症状。
- [ ] 运行 `python -m pytest tests/test_api.py -q`，观察失败。
- [ ] 实现SQLite事务、患者代号和初复诊、规则三级审核/发布/撤回、快照、医生采用修改驳回及修改后风险重查。
- [ ] 集成知识API，限制上传大小/文件类型，不返回任意本机路径；运行全套pytest。
- [ ] 仅合成演示规则可预置published，明确synthetic；真实方证仅预置带页码的候选研究卡。
- [ ] 协调者提交。

### Task 4: 最小Pi通道与秘密保护

**Files:** `ai-bridge/package.json`、锁文件、`ai-bridge/bridge.mjs`、`app/model.py`、`app/secrets.py`、`tests/test_model.py`。

**Interfaces:** bridge从stdin读一条请求JSON和可选cancel，stdout逐行事件JSON；Python保存已完成模型补充，不改规则结果。HTTP接口见API契约。

- [ ] 先测试：外发未授权拒绝、地址/重定向边界、密钥遮蔽、断流/失败/取消不记成功、非法引用拒绝、秘密DPAPI往返。
- [ ] 锁定并安装Pi AI 1.3.0，只注册OpenAI兼容provider，不安装编码Agent工具。
- [ ] 模型配置加密保存；固定合成文本连接测试；病例补充仅发送明确允许的结构化字段，资料片段发送另行许可。
- [ ] 本地协议测试服务器完成真实HTTP/流式/取消集成测试；这不是供应商真实调用验收。实际供应商测试保留设置页入口，待用户配置。
- [ ] 全套pytest及Node自检通过；协调者提交。

### Task 5: 医师工作台与备份恢复

**Files:** `frontend/**`（含构建与类型配置）、`app/backup.py`、`scripts/restore_backup.py`、`tests/test_backup.py`。

**Interfaces:** Vue使用API契约；构建输出`frontend/dist`由FastAPI提供。备份加密且不含模型凭据；恢复只到空目录。

- [ ] 先测加密/密码错误/目标非空/完整性/路径穿越拒绝，再实现备份与恢复。
- [ ] 完成资料搜索、页面校核与证据卡；病例四诊表及多候选比较；规则JSON受限编辑和审核；加减草稿；复诊时间线；模型连接、许可和取消；备份下载。
- [ ] 页面区分资料未核实、模型提议、规则条件结果和医生决定，始终显示模拟验证模式；危险或核查未完成有明确状态。
- [ ] 运行 `npm.cmd run build`（含类型检查）；以真实服务做浏览器流程检查。
- [ ] 协调者提交。

### Task 6: 集成、审查与本机交付

**Files:** `README.md`、`start.ps1`、`start.cmd`、验收报告、源码包及启动入口。

- [ ] 全量pytest、前端构建、Pi协议集成、七份资料计数、搜索和PDF回跳、初复诊和审核、加密备份实际恢复。
- [ ] 独立审查代码/数据流/安全边界，修复重要问题并补回归测试。
- [ ] 在本机127.0.0.1启动，实查界面与实际流程，不以静态页面替代验收。
- [ ] 输出源码包（不含PDF/病历/凭据）、启动入口、已通过与未完成项；记录专业审核与真实模型调用的外部依赖。

执行方式：按已授权设计连续实施；独立文件并行、集成顺序执行，不再追加流程确认。无现有仓库，已新建独立工程及`codex/clinical-engine`分支。此计划不引入云端发布。
