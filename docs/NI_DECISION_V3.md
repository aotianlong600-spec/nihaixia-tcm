# 倪氏原文映射与决策图：本轮执行契约

用户2026-11-05新要求为本轮规范：个人自用，无规则审核、签名或发布审批；不扩界面。继续现有工程并实际实现、验证。AI理解不是医学证据，开源医学数据保持外部来源。

## 方案与边界

采用SQLite内不可变decision_packages包，保持原件和历史；不搭图数据库或新增服务。原文锚点→逐项断言→条件与方剂版本→鉴别/细化边形成决策图，按来源条件分别计算，保留多个候选及未知；不设置固定八纲/六经医学先后顺序。原有加权仅召回。

先完整对应同一倪注伤寒论原件的桂枝、加葛根、葛根、麻黄及厚朴杏仁关联组。全部17来源仍可检索，未对应的开源314方不冒充倪氏已映射条目。书目标题归属不等于逐句作者核验。

## 数据包契约（format_version=1）

- id:string, version:positive int, title:string；同id/version内容不可覆写；换内容用新version。
- anchors:[{id,source_id,unit_no,start,end,quote,unit_sha256,layer,attribution,version_label,reading?,reading_note?}]。start/end为原始单元Unicode码点半开区间，quote逐字连续且unit_sha256等于整单元raw_text哈希；layer为classic_clause/ni_commentary/ni_case/compiler_annotation/reference_author/open_source_summary/ai_inference。阅读重排/图像转录另列reading_note，不能伪称连续原文。
- claims:[{id,kind,text,anchor_ids,inference,scope,limitations:[]}]. kind为support/necessary/exclusion/course/differential/treatment/identity/processing/dose/preparation/modification/interpretation；inference为literal/interpretation/visual_transcription。每个断言必须有真实锚点；必要条件只可用kind=necessary且inference=literal的明示来源。校验定位不等于自动医学语义认证。
- formulas:[{version_id,catalog_id,name,identity_claim_ids,components:[{name,processing,source_dose,source_unit,provenance:{name:claim_ids,processing:claim_ids,source_dose:claim_ids,source_unit:claim_ids}}],preparation:[{text,claim_ids}],limitations:[]}]. 非空字段须分别引用适类断言；未知null、出处空数组，不换量。同方异版独立version_id。
- nodes:[{id,label,kind,scope,scope_claim_ids,formula_version_id?,conditions:[{id,role,expr,claim_ids}],questions:[{key,question,reason,claim_ids}],cases?:[{id,label,expr,claim_ids,scope}],treatment_claim_ids?:[],limitations:[]}]. role为required/support/exclude/course；expr沿用engine._expr有限语法，禁止脚本。support为假不全局排除；required/course未知保留pending；任何冲突明确标conflict；排除只执行明确来源。kind可pattern/syndrome/treatment，scope仅有文字时不编造年龄病程范围。
- edges:[{id,from,to,relation,claim_ids,note}]. relation为differential/refines/coexists/treatment；图仅执行声明条件，无隐含父节点必选。细化失败或未知保留上层及其他候选，输出边轨迹。
- modifications:[{id,base_version_id,target_version_id?,trigger,claim_ids,actions:[{operation,target_name?,target_processing?,component?,claim_ids}],limitations:[]}]. trigger沿用表达式，source-backed范围是该条文情境、非通用必要。operation add/remove/replace/adjust；component使用相同字段级provenance。缺量不补。基方身份/炮制不明、动作冲突或目标版本存在未解释差异时整组不应用；照样计算差异，列applied/unapplied/missing/conflicts。

## 程序接口

app/decision.py：initialize(conn)、import_package(conn,payload)->counts、load_packages(conn)->list、digest(conn)->str、coverage(conn)->dict、evaluate(conn,facts,package_id=None)->dict、preview_modifications(conn,package_id,base_version_id,modification_ids,facts)->dict。

evaluate返回packages（含id/version/digest/snapshot）、nodes（条件trace/source绑定、status、formula_version_id）、edges轨迹、questions、formulas（来源版本、逐字段依据）、anchors、claims、ignored_facts、source_issues、safety(status=incomplete)、coverage。状态为compatible/clue/pending/excluded/conflict/source_invalid；compatible仅可来自至少一个完整来源case符合，clue仅有支持线索；case表达式不是所有应用的全局必要条件。compatible不是诊断或可直接服用。数据包缺失时为空且明确未覆盖。

导入与当前执行均核对来源原文哈希。表达式复用_engine底层，禁止调用旧published规则入口。补问只针对未知/冲突当前患者信息，已知不重复；raw聊天不自动变成已确认事实。

## 集成

个人context追加decision_graph完整冻结结果与decision_digest；模型收到同一份trace和书证层级，并优先解释已映射版本。输出formula_version_id若有须在本次图中，程序回填该版逐字段来源与煎服，不允许跨版；无映射的开源方标外部未对应，不能升级为倪氏规则。新增GET /api/decision/coverage、GET /api/decision/packages、POST /api/decision/evaluate、POST /api/decision/modifications/preview；保持旧接口与备份格式，数据包在DB自动随备份保存，历史消息保留快照。

## 验收

正常支持、关键缺失、明示反证、冲突、既往/他人误用、同方异版混入、信息不足多候选与补问；或不改成且；全部字段引用、来源篡改失效、动作实际差异/冲突回退、历史及旧备份兼容。软件测试不是医学有效性验证，未接真模型如实说明。

来源层约束：每个可执行断言至少有对应原件层锚点；单独AI推演或开源摘要可作资料但不得支撑情境、硬条件、动作或方药字段；个案不得单独支撑全局必要/排除/病程。原作者/来源层标签是编制声明，不是作者身份或医学意义的自动认证。
