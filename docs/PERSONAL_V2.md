# 个人自用版：资料库与AI辨证方案

2026-11-05，按用户最新指令覆盖早期“规则审核/发布”产品流程。资料选定范围已确定，不重复索要选书或本次本地处理确认。

## 目标

用户输入症状和四诊，经方与方证为底层：检索倪氏资料及指定参考书、匹配经方线索、AI有针对性追问，给出候选证候、候选方与加减依据及原文入口。个人保存记录，不需要医生身份、规则审批或发布。

截图只作为交互参考，不导入图中个人病史。采用书库问答/问诊单/经方候选/历史记录的简洁工作台，去掉规则审核、临床发布数、合成演示菜单和重复审批标记。保留自动的来源、药名、计量、冲突与风险检查；不能把自编权重或模型自评当诊断概率。

## 已确定实现选择

- 保持FastAPI、SQLite、Vue、Pi接口。原PDF表与历史快照不迁移破坏；新增非PDF原件及行/段锚点、资料角色标签。
- 新9份文件全部纳入：5PDF（1101页）+2TXT+DOCX+DOC。扫描519页做CPU本地OCR，与原提取/人工订正分开。
- 指定四开源库只读取官方快照。NiApp的Apache2医学数据保留许可和逐条来源，人工分值仅做候选召回；RAG与实体关联借鉴其余项目，不直接部署Neo4j/Qdrant/LangGraph整套服务。
- AI是主推演层：选取来源上下文后，补问/辨证/方药与加减草案；自动校验负责约束和标记，不要求用户审批每条知识。
- 个人健康记录保存在本机，密钥DPAPI，默认不外发。配置供应商后用户主动发送才调用模型；不读其他应用的凭据。无真实接口时明确待配置，不伪造AI答案。

## V2 API契约

沿用`GET /api/session`、HttpOnly cookie及写操作`X-CSRF-Token`，`/api/model/config`、`/api/model/jobs/{id}`、cancel、backup。

### 统一资料库

- `GET /api/library/sources` -> `{items:[{id,title,format,units,pdf_pages,corpus_role,has_ocr,warning}]}`。format为pdf/txt/doc/docx/github；pdf_pages非PDF为null，不能把段落伪称原书页。
- `GET /api/library/search?q=&source_id=&limit=30` -> `{items:[{source_id,unit_no,title,format,physical_page?,locator:{kind,start,end},snippet,corpus_role,preview_url,source_url?,warning}]}`。
- `GET /api/library/sources/{id}/units/{n}` -> `{source_id,unit_no,title,format,locator,corpus_role,raw_text,ocr_text?,corrected_text?,image_url?,original_url?,source_url?,warning}`。PDF保留原件图像；文本显示原始行/段区间。无审批按钮。
- `GET /api/library/sources/{id}/original` 下载哈希校验原件（Word只下载不执行宏）；GitHub条目跳固定提交来源。

### 方证经方库

- `GET /api/formulas?q=&limit=30` -> `{items:[{id,name,syndrome,six_meridian,components,modification_notes,contraindications,source_refs}]}`。
- `GET /api/formulas/{id}` 返回单方。
- `POST /api/formulas/match` `{facts:[],query:'',limit:8}` -> `{items:[{id,formula_id,name,syndrome,six_meridian,matched_features,missing_features,contradictions,score,score_explanation,components,modification_notes,contraindications,source_refs}]}`。界面显示支持/缺项/反证，不显示“置信度XX%”。
- component字段：name,processing,source_dose,source_unit,source_ref。剂量是来源原字符串，可null，不自动转换古今量。

### 自用问诊记录

`Intake`至少支持：sex（male/female/unknown）,age_years（可null）,chief_complaint,body_locations[],pain_natures[],symptoms[],duration,tongue,pulse,sleep,appetite,stool,urine,medical_history,medications,allergies,notes。全部可缺省为未知/空，不能自动当阴性。可附facts[]（旧Fact结构key/state/verified/scope/subject，verified在个人版表示用户已确认，不表示医生认证）。

- `POST /api/consultations` `{title?:string,intake?:Intake}` -> `{id,title,intake,revision:1,messages:[],created_at,updated_at}`。
- `GET /api/consultations` -> `{items:[{id,title,revision,created_at,updated_at}]}`。
- `GET /api/consultations/{id}` -> 完整记录，messages包含`{id,role:user|assistant,text,result?,job_id?,created_at,stale?}`。
- `PUT /api/consultations/{id}` `{expected_revision,intake}` -> 新revision；旧输入不覆盖新输入。
- `POST /api/consultations/{id}/messages` `{text,expected_revision?:number}` -> `{consultation,message,revision}`（先本地保存）。
- `GET /api/consultations/{id}/context` -> `{facts,formula_candidates,evidence:[{id,title,text,locator,source_id,unit_no,format,corpus_role,preview_url?,source_url?,content_sha256}],coverage}`。只读预览AI会用的书证，不自动调用模型。

### AI问诊任务

`POST /api/model/jobs` 扩展`{purpose:'consult',consultation_id,allow_send:true}`；test/explain旧能力保留但无旧审批流程依赖。

轮询返回原job字段并增加`result`与`consultation_id`。成功result如下，字段缺项可空但不造值：

```json
{
  "stage":"follow_up",
  "summary":"当前判断与缺项摘要",
  "questions":[{"key":"sweating","question":"是否出汗？","reason":"有助于鉴别候选方证"}],
  "syndromes":[{"name":"候选证候","six_meridian":"","eight_principles":"","supporting_symptoms":[],"contradictions":[],"missing_information":[],"brief_reason":"","evidence_ids":[]}],
  "formulas":[{"formula_id":null,"name":"候选方","reason":"","components":[{"name":"药名","processing":null,"source_dose":null,"source_unit":null,"source_ref":null}],"modifications":[{"action":"add","herb":"","replacement":null,"trigger_symptoms":[],"source_note":"","evidence_ids":[]}],"preparation":null,"evidence_ids":[]}],
  "risks":[],"limitations":[],"evidence_ids":[]
}
```

stage为follow_up/assessment。信息不足先补问，不强制三轮、不强制出方；个人症状不等于唯一疾病。候选方必须来自本次经方/原文上下文；来源剂量可列文献原量，缺失不补写，不把古量直接作个人日量。AI推演与引用内容分别显示。

只给模型发送本次必要症状、用户提供的健康背景、选取书证与经方条目；不发送文件路径、密钥或无关身份。结构/引用合法只表示程序检查通过，不保证医学结论成立。症状或来源变化后结果保留历史并标旧。

## 实施任务与验证

1. 新资料复制/哈希/原始锚点与本地OCR，报告逐文件实际入库与失败项。
2. 非PDF库、OCR独立字段、资料角色、统一检索/预览、限定多来源RAG上下文；回归旧PDF与备份。
3. NiApp医学库导入、症候/别名/必要条件与反证匹配、原量/加减结构，记录实际函数和不可当概率的权重。
4. 自用会话/问诊单与AIconsult任务，冻结输入/书证/输出，结构化响应和失败/取消/旧结果验证。
5. 界面重组移除规则审核；真实浏览器走新会话、结构问诊、书库、经方和历史；无接口时诚实提示。
6. 全测试、独立代码审查、实际混合资料备份恢复、更新源码包/使用说明。

执行按用户明确授权连续推进，独立文件并行、协调者统一集成和Git提交；不再索要规则审批或资料选择确认。
