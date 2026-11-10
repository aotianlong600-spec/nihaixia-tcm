# 倪氏资料辨证研究的职责与来源边界

## 已核对的参考实现

倪海厦 skill 的角色是作者风格 persona、话题路由和文字推理步骤，不是多智能体执行器。参考版本为 [5506209 的 SKILL.md](https://github.com/jangviktor-web/nihaixia/blob/5506209ac1ff767c79ddaa816ccb0ef7b8e4ddbb/SKILL.md#L487)。其中强制落方、隐藏定位、按常例补药或换算的要求不进入本系统；原文、整理与推演分别保留。

[nihaixia-app 的规则引擎](https://github.com/jangviktor-web/nihaixia-app/blob/e29610fd9be0494d51ffb27e61d3ea0b32b24002/lib/engine/rule_engine.dart#L17)可参考候选、鉴别和回退结构，必要条件必须重新对应本机原件，不能直接继承开源权重或把排序分当概率。

[tcm-rag-agent 的 LangGraph 编排](https://github.com/djp0417/tcm-rag-agent/blob/9cc954ed16e912ed8452154bcc6ff7dc4e24c08c/app/multiagent/graph.py#L53)有真实角色、补问和回退，但其专家分支偏食疗、经络及运动；本轮不引入这些分支或额外模型请求。

## 当前工程分工

以下是本系统的工程职责，不是声称倪师提出了这些角色。当前采用一次模型请求结合程序校验，并未实现多模型独立会诊。

| 职责 | 执行位置 | 约束 |
| --- | --- | --- |
| 患者事实整理 | personal.facts_from_intake、engine._facts、prepare_task | 当前、既往、他人、未核对分开；否认、未知和冲突保留；症状勾选不被背景同名记录吞掉 |
| 原文检索 | library.retrieve_context、decision_support.consultation_context | 检索词不变成患者事实；原件哈希、版本、物理页和已登记印刷页随来源返回 |
| 方证鉴别与补问 | decision.evaluate、decision._questions、模型解释 | 保留多个候选和回退；排序按冲突、来源条件和已声明鉴别边，属于程序结构优先级 |
| 方剂版本及加减执行 | decision_support.bind_formula、decision.preview_modifications | 药味、炮制、来源原量和煎服分开对应；跨版本或动作冲突整组回退；不换算个人日量 |
| 引用与结果核对 | personal.validate_consult_result、decision_support.bind_question | 引用限定同次冻结书证；只有相同 key 和原问题文字才能绑定图谱补问；模型自报来源不可信 |

## 本轮补问算法

补问按“事实 key + 原问题文字”归组，同一问题的每个包、版本、节点、断言及未决条件分别保留在 source_bindings；同名节点不跨包混为一个身份，不同问法不静默替换。node_ids 仅保留旧接口的显示兼容，身份以完整 binding 为准。

优先澄清显式冲突，其次检查来源声明的必要、排除或病程约束，再参考同一包版本中的有效鉴别关系和候选覆盖；同级保留稳定顺序。这不估计信息增益、诊断概率或医学紧急程度，也不改变原有条件的 AND/OR。

AI采用图中原问题时，程序回填相应原文引用与来源层级；自拟问题仍是 AI 推演。开源或 AI 锚点不会因进入决策图而改称原文依据。改写问题不能仅凭同一 key 自动继承原文身份。

冻结上下文保存分析处理版本。旧版本记录不改写、不删除；因事实分层与补问契约已变化，旧结果提示过期，新的问诊请求重新计算。

## 新文稿的进度口径

新增内经上下册是两个独立哈希版本，共306物理页、301个已交叉核对的印刷页码。原文件名“皇帝内经”保留，规范标题另记为“黄帝内经”。旧461页内经不覆盖。

本轮完成原件保存、逐页文本导入和定位；不把这些计为新增医学断言或可执行方证规则。正文可提取不等于逐字校勘完成。混合页面中的非临床讨论保留在原件中，不能据此自动生成临床条件。

验证使用合成事实和冻结来源检查。软件回归通过不证明临床有效性；全面药物风险库仍未完成。
