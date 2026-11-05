# 倪氏逐项溯源决策图 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** 在既有个人工程实现首组原文映射、多候选鉴别、确定性版本和加减执行。

**Architecture:** 不可变包存SQLite；核对原始单元锚点与逐字段断言，调用原有有限表达式底层。个人会话冻结本次图、来源和结果，旧目录保留外部身份。

**Tech Stack:** 既有Python/FastAPI/SQLite，不加依赖。

**Spec:** docs/NI_DECISION_V3.md（用户已明确要求连续实现，无重复方案审批）。

## Global Constraints

不改原件、不破坏旧记录/备份、不加规则审核、不扩UI、不假装全库医学映射完成；原量不换算，缺安全覆盖为incomplete。

## Review Focus

必要条件出处、OR误AND、缺失/冲突/历史误用、方剂版本混入、字段证据漏项。

## Tasks

- [ ] 资料核对：work/ni-decision-v3/source-map.json真实锚点，生成首包与逐字段claims；保留剂量差异。
- [ ] app/decision.py + tests/test_decision.py：先失败测试，再导入定位/引用校验、四态多候选/补问/边回退、不可变版本、差异计算。验证所有上列输入类。
- [ ] scripts/import_decision.py 与app/personal.py：新增API、context/AI同快照、逐字段映射版本验证；tests/test_personal.py与consult jobs回归。
- [ ] 真实库导入；完整Python、前端/桥接兼容测试；不可变包备份恢复、独立代码及资料审查。
- [ ] outputs区分导入/已映射/结构化/可执行/冲突口径，更新说明与源码包。
