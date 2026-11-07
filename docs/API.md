# 历史 API 兼容说明

本页保留旧接口契约，供现有调用方维护。当前工作台参见 [问诊接口](PERSONAL_V2.md)、[辨证决策图](NI_DECISION_V3.md) 和 [安卓本地运行接口](MOBILE_RUNTIME_CONTRACT.md)。

所有接口同源`/api`，JSON UTF-8；列表返回`{"items": [...]}`。错误使用HTTP状态及`detail`。时间ISO8601，物理页1-based。禁止客户端提供本机文件路径。

## 原文映射决策图

当前主契约见 [NI_DECISION_V3.md](NI_DECISION_V3.md)，包括 /api/decision/coverage、packages、evaluate、modifications/preview，及问诊上下文中的冻结图与字段来源。

## 会话

`GET /api/session` 初始化HttpOnly SameSite=Strict会话cookie，返回`{csrf_token,mode:"personal",version:"0.3.0"}`。其他API需cookie；POST/PUT需`X-CSRF-Token`。前端fetch credentials same-origin。`GET /api/status`仅公开版本/运行状态。

## 规则核心字典

Fact: `{key:string,state:"present"|"absent"|"unknown"|"conflict",raw?:string,source?:"patient"|"clinician"|"test",observed_at?:string,scope?:"current"|"history",verified:boolean,value?:string|number|null,unit?:string}`。只有verified且current事实参与判断，省略scope视current。

Expr: `{fact:string,state?:"present"|"absent"}` 或 `{fact:string,op:"gt"|"gte"|"lt"|"lte"|"eq",value:string|number,unit:string}` 或 `{all:Expr[]}` / `{any:Expr[]}` / `{not:Expr}`。未知NOT仍未知；禁止空all/any及任意脚本。

Rule: `{id:string,version:number,title:string,kind:"pattern"|"red_flag"|"safety"|"modification",status:"draft"|"published"|"withdrawn",synthetic:boolean,scope:{min_age?:number,max_age?:number,description:string},required:Expr,support:Expr[],excluded?:Expr,evidence_ids:string[],formula_id?:string,formula:Drug[],actions:Action[],base_formula_id?:string,description:string}`。非 synthetic 的启用规则须有真实原文证据。为兼容旧存档，启用状态仍编码为 `published`；草稿和撤回的规则不执行。

Drug: `{name:string,processing:string,amount:string,unit:string,basis:"per_dose"|"per_day"|"per_course",evidence_ids:string[]}`。amount十进制字符串，禁止NaN/Infinity/负数/零；不默换原单位。Action: `{operation:"add"|"remove"|"replace"|"adjust",target?:{name:string,processing:string},drug?:Drug}`。加减规则按传入事实判定，绑定base_formula_id；同一药物互斥动作阻止整体应用。

Context: `{age_years?:number,pregnancy?:"yes"|"no"|"unknown",allergies?:string[],medications?:string[],simulation?:boolean}`。空数组不代表安全信息已完整，核查结果必须声明覆盖。

`analyze(...)`返回`{candidates:[{rule_id,title,status:"matched"|"not_matched"|"pending"|"conflict"|"not_applicable",required,excluded,support,missing:string[],conflicts:string[],evidence_ids,formula_id,formula}],urgent:boolean,questions:string[],safety:object,trace:object}`。required/excluded/support保留判定轨迹，值使用`true`/`false`/`null`。danger命中时candidates中不保留可用formula。

`apply_modifications(...)`返回`{formula:Drug[],applied:list,conflicts:list,pending:list}`；冲突或缺条件不输出假装成功的合并结果。`check_formula(...)`返回`{status:"risk"|"incomplete"|"covered_no_hit",issues:list,coverage:list,uncovered:list}`。缺安全库默认incomplete，不得safe。

## 资料

- `GET /api/documents`：`{items:[{id,title,sha256,physical_pages,reviewed_pages,status,author_status,warning}]}`。
- `POST /api/documents`：multipart `file`，上限50MiB；返回文档及重复导入标记。
- `GET /api/search?q=&document_id=&limit=30`：`{items:[{document_id,title,physical_page,snippet,review_status,warning,pdf_url}]}`；pdf_url为同源PDF路径加`#page=N`。
- `GET /api/documents/{id}/pdf`：只返回登记原件。
- `GET /api/documents/{id}/pages/{n}`：`{document_id,physical_page,raw_text,corrected_text,review_status,kind,printed_page,warning}`。
- `POST /api/documents/{id}/pages/{n}/review`：可选的原文订正操作，`{corrected_text,kind,reviewer?,printed_page?,note?}`，保留 raw_text。
- `POST /api/evidence`：`{document_id,physical_page,quote,kind,reviewer?,printed_page?}`；返回`{id,...}`，quote 须逐字匹配该页当前文本，可直接引用原文。
- `GET /api/evidence`：`{items:[...]}`。

Knowledge函数返回值遵循以上字段。`init_knowledge(conn,data_dir)`创建自身表，数据目录下`originals`保存哈希命名原件，函数不自行提交事务。`import_audit`读取前轮审计manifest（含本机路径），仅供受信本地CLI使用，API不暴露此入口。search返回普通文字而非HTML。`get_page`越界返回None，其他非法输入抛ValueError。文档id使用稳定sha256。

## 规则管理

- `GET /api/rules` 返回 `{items:[Rule加reviews对象、created_at]}`；`reviews` 仅保留历史数据。
- `POST /api/rules` `{rule:Rule}`：默认直接启用；显式指定 `status:"draft"` 则只保存草稿。已有规则使用新 id/版本替换。
- `POST /api/rules/{id}/activate`：启用已有草稿，无需请求体。
- `POST /api/rules/{id}/withdraw`：撤回规则，请求体 `{reviewer?,note?}` 可省略。

## 病例与分析

- `GET/POST /api/patients`；创建`{code,notes?:string}`，返回`{id,code,notes,created_at}`。code为病例代号。
- `GET /api/visits?patient_id=...`；`POST /api/visits` `{patient_id,previous_visit_id?:string,chief_complaint,facts:Fact[],context:Context,clinician?}`，返回完整 visit，初始 revision=1。
- `GET /api/visits/{id}` 返回 visit 及 `analyses:[]`、`decisions:[]`；`PUT /api/visits/{id}` 提交 `{expected_revision,chief_complaint,facts,context,clinician?}`，版本不符 409。服务器 revision 递增。
- `POST /api/visits/{id}/analyze` `{expected_revision,selected_rule_ids?:string[],base_rule_id?:string,modification_ids?:string[]}`。空 selected 使用全部已启用规则；base_rule_id 是用户选择的基础方规则。返回 `{id,visit_id,visit_revision,created_at,result,input_snapshot,rule_snapshot,evidence_snapshot,stale:false}`。
- `POST /api/analyses/{id}/decision` `{decision:"adopt"|"modify"|"reject",clinician?,notes?,final_formula?:Drug[]}`；旧 revision 拒绝。修改方药重新 check_formula 后存入独立记录，返回决定加 `risk_check`。
- `GET /api/patients/{id}/timeline`返回`{items:[visit含分析与决定]}`。复诊事实从空开始，界面另列旧访次供核对。

## 模型与备份

- `GET /api/model/config`返回`{base_url,model,enabled,allow_external,allow_evidence,has_key,key_hint}`；绝不返回秘密。
- `PUT /api/model/config` `{base_url,model,api_key?:string,enabled,allow_external,allow_evidence}`。省略/空api_key保留已有。仅HTTPS远端或HTTP loopback，无重定向。
- `POST /api/model/jobs` `{purpose:"test"|"explain",analysis_id?:string,allow_send?:boolean}`；返回`{id,status}`。test只发固定合成文本；explain需config许可及allow_send，发送范围为非身份结构化facts和规则结果，资料原文另需allow_evidence。不能发送code/notes/chief_complaint/raw。
- `GET /api/model/jobs/{id}` `{id,status:"queued"|"running"|"completed"|"failed"|"cancelled",text,error?,usage?,validated?}`。部分text仅预览；completed且validated才保存为模型补充。模型解释预期JSON`{summary:string,questions:string[],evidence_ids:string[]}`，引用须为该分析的证据。
- `POST /api/model/jobs/{id}/cancel` 返回状态；不表示远端立即停止计费。
- `POST /api/backup` `{password}`下载加密备份（最少12字符）；备份只含数据库、originals和哈希清单，排除密钥。恢复CLI仅空目标目录，不在浏览器一键覆盖。

## 模式与演示数据

旧接口预置 `synthetic` 演示规则。首次创建访次的 `facts` 为空。旧概览接口返回文档数、物理页数、发布规则数和 `simulation` 状态。

## 已实现的补充与校准（2026-11-05）

- Fact增加`subject:patient|family|other|unknown`，默认patient；非本人、既往或未核实事实不参与当前规则及文献对照，不进入模型结构化事实发送。
- `apply_modifications(formula, modifications, facts, base_formula_id='', context=None)`；API传同一访次context，年龄限定不会在加减阶段丢失。
- `GET /api/research` 返回已导入的研究条目。原文症候对照写入分析的 `result.literature_candidates`，按来源页序返回，并分别列出反证和缺项。
- `GET /api/documents/{id}/pages/{n}/image`同源鉴权返回该物理页PNG，尺寸不超过2000×2800像素；全部PDFium调用使用同一进程锁。原始页图像不会改变提取文本或校核状态。
- `GET /api/overview`增加`research_entries`和`clinical_published_rules`，将合成演示与真实规则发布数量分开。
- 模型job的`stale`和`dependency_warnings`在完成和读取时动态核对；发送前也拒绝已失效分析。重启后GET job可读取持久化的已完成记录；访次/时间线增加`model_supplements`。
- 检查与写入使用短SQLite写事务序列化；每请求独立连接允许ASGI线程交接。已发布规则的顶层、逐药和动作证据并集均被冻结及检查失效。
- 备份从数据库快照的登记集读取原件，创建和恢复都核对哈希及完整性，大小口径包括清单；不复制未登记孤儿文件。
- 启用规则时仍检查必要条件是否定义、加减动作是否完整，以及原文证据是否可定位。
