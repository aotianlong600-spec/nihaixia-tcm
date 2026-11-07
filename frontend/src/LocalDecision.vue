<script setup lang="ts">
import {computed} from 'vue'
import {conditionLabel,traceLabel,sourceRows,formulaClaimIds,modificationClaimIds,modificationLabel} from './localDecisionState'
import {locatorLabel,roleLabel,previewComponentLabel,actionLabel} from './personalState'
const props=defineProps<{graph:any;evidence?:any[];revision?:number}>()
const emit=defineEmits<{(e:'source',value:{source:string;unit:number}):void}>()
const nodes=computed(()=>props.graph?.nodes||[])
const statuses:Record<string,string>={compatible:'来源情境符合',clue:'支持线索',pending:'信息待补',excluded:'当前条件不符',conflict:'信息冲突',source_invalid:'来源校验异常'}
const roles:Record<string,string>={required:'来源必要条件',support:'支持条件',exclude:'排除条件',course:'病程条件'}
const rows=(identity:any,ids:string[])=>sourceRows(props.graph,identity,ids,props.evidence)
const nodeClaims=(n:any)=>[...(n.scope_claim_ids||[]),...(n.treatment_claim_ids||[]),...[...(n.conditions||[]),...(n.case_traces||[]),...(n.questions||[])].flatMap((c:any)=>c.claim_ids||[])]
const questionClaims=(q:any)=>[...(q.source_bindings||[]).map((b:any)=>({identity:b,ids:[...(b.claim_ids||[]),...(b.condition_refs||[]).flatMap((c:any)=>c.claim_ids||[])]})),...(q.priority?.differential_refs||[]).map((r:any)=>({identity:r,ids:r.claim_ids||[]}))]
const layerLabel=(layer:string)=>({classic_clause:'经典条文',ni_commentary:'倪师讲解',ni_case:'倪师医案',compiler_annotation:'整理者注释',reference_author:'参考原作者'} as Record<string,string>)[layer]||roleLabel(layer)
const sourceLabel=(a:any)=>`${a.evidence?.title||a.attribution||'来源原件'} · ${a.evidence?locatorLabel(a.evidence):`单元 ${a.unit_no}`}`
function open(a:any){emit('source',{source:a.source_id,unit:a.unit_no})}
</script>
<template>
<section class="panel local-decision" aria-label="本地原文方证分析">
 <h2>本地原文方证分析</h2>
 <p class="hint">依据已保存、已核对的当前本人事实执行。输入框文字仅用于检索，不自动成为患者事实。{{revision!=null?`记录版本 ${revision}。`:''}}</p>
 <p class="hint">当前映射 {{graph?.coverage?.mapped_formulas??0}} 个来源方剂版本、{{nodes.length}} 个节点，覆盖仍不完整；以下是来源条件执行与组成差异，不是诊断概率或个人处方。用药安全资料尚不完整。</p>
 <p v-if="!nodes.length">尚无可执行的原文映射图。外部经方目录不计作原件映射，仍可查阅书库。</p>
 <div v-for="issue in graph?.source_issues||[]" :key="issue.package_id+issue.anchor_id" class="warning">来源异常：{{issue.reason}}；包 {{issue.package_id}} · 锚点 {{issue.anchor_id}}</div>
 <article v-for="n in nodes" :key="`${n.package_id}@${n.package_version}:${n.id}`" class="result-card">
  <h3>{{n.label}} · {{statuses[n.status]||n.status}}</h3>
  <p class="hint">{{n.scope}} · 来源包 {{n.package_id}} / {{n.package_version}}<template v-if="n.formula_version_id"> · 方剂版本 {{n.formula_version_id}}</template></p>
  <p v-for="c in [...(n.conditions||[]),...(n.case_traces||[])]" :key="`${c.role||'case'}:${c.id}`">
   <strong>{{roles[c.role]||'来源情境'}} · {{traceLabel(c.trace)}}</strong>：{{c.label||conditionLabel(c.expr)}}
   <small>（{{c.id}}；断言 {{c.claim_ids?.join('、')||'未提供'}}）</small>
   <span v-if="c.trace?.missing?.length">；缺项：{{c.trace.missing.join('、')}}</span><span v-if="c.trace?.conflicts?.length" class="warning">；冲突：{{c.trace.conflicts.join('、')}}</span>
  </p>
  <details><summary>逐项断言与来源依据</summary>
   <div v-for="row in rows(n,nodeClaims(n))" :key="row.id" class="source-claim">
    <p><strong>{{row.id}}</strong>：{{row.claim?.text||'来源断言未提供'}}</p><p v-if="row.missing" class="warning">来源断言或锚点缺失，不能据此判断。</p>
    <div v-for="a in row.anchors" :key="a.id"><button type="button" class="text-link" @click="open(a)">{{sourceLabel(a)}}</button><small> · {{layerLabel(a.layer)}} · {{a.version_label}}</small><blockquote>{{a.quote}}</blockquote><p v-if="a.reading" class="hint">整理阅读：{{a.reading}}</p></div>
   </div>
  </details>
 </article>
 <div v-if="graph?.questions?.length" class="result-card"><h3>本地待补与鉴别问题</h3>
  <div v-for="q in graph.questions" :key="q.key+q.question">
   <p><strong>{{q.question}}</strong> {{q.reason}}<small v-if="q.priority?.clarify_conflict"> · 优先澄清矛盾</small><small v-else-if="q.priority?.source_constraint"> · 补齐来源约束</small></p>
   <template v-for="(binding,index) in questionClaims(q)" :key="index"><template v-for="row in rows(binding.identity,binding.ids)" :key="row.id"><span v-for="a in row.anchors" :key="a.id"><button type="button" class="text-link" @click="open(a)">{{sourceLabel(a)}}</button><small> · {{layerLabel(a.layer)}}</small> </span></template></template>
  </div>
 </div>
 <details v-if="graph?.formulas?.length" class="result-card"><summary>文献方剂版本与组成（来源原量，非个人日量）</summary>
  <article v-for="f in graph.formulas" :key="`${f.package_id}@${f.package_version}:${f.version_id}`">
   <h3>{{f.name}}</h3><p class="hint">包 {{f.package_id}} / {{f.package_version}} · 版本 {{f.version_id}}。版本资料可查阅，不表示当前适用。</p>
   <p v-for="(c,index) in f.components||[]" :key="index">{{previewComponentLabel(c)}}<small>；药名依据 {{c.provenance?.name?.join('、')||'未提供'}}；炮制依据 {{c.provenance?.processing?.join('、')||'未提供'}}；原量依据 {{c.provenance?.source_dose?.join('、')||'未提供'}}；单位依据 {{c.provenance?.source_unit?.join('、')||'未提供'}}</small></p>
   <p v-for="(p,index) in f.preparation||[]" :key="index">煎服来源说明：{{p.text}}<small>；断言 {{p.claim_ids?.join('、')||'未提供'}}</small></p>
   <details><summary>方剂字段来源</summary><div v-for="row in rows(f,formulaClaimIds(f))" :key="row.id"><p>{{row.id}}：{{row.claim?.text||'来源断言未提供'}}</p><div v-for="a in row.anchors" :key="a.id"><button type="button" class="text-link" @click="open(a)">{{sourceLabel(a)}}</button><small> · {{layerLabel(a.layer)}}</small><blockquote>{{a.quote}}</blockquote></div><p v-if="row.missing" class="warning">字段来源未完整提供。</p></div></details>
   <p v-for="limitation in f.limitations||[]" :key="limitation" class="hint">{{limitation}}</p>
  </article>
 </details>
 <div v-if="graph?.modification_previews?.length" class="result-card"><h3>本地经方加减差异</h3>
  <article v-for="item in graph.modification_previews" :key="`${item.package_id}@${item.package_version}:${item.modification_id}`">
   <h4>{{item.modification_id}} · {{modificationLabel(item.preview)}}</h4><p class="hint">包 {{item.package_id}} / {{item.package_version}} · 基方版本 {{item.base_version_id}}</p>
   <p v-if="item.preview.missing?.length">缺项：{{item.preview.missing.join('、')}}</p><p v-for="conflict in item.preview.conflicts||[]" :key="conflict" class="warning">{{conflict}}</p>
   <p v-for="m in item.preview.unapplied||[]" :key="m.id">未应用：{{m.reason}}</p>
   <p v-for="trace in item.preview.traces||[]" :key="trace.id">触发条件：{{conditionLabel(trace.trace?.expression)}} · {{traceLabel(trace.trace)}}</p>
   <p v-for="(d,index) in item.preview.diff||[]" :key="index"><template v-if="d.operation">差异计算 · {{actionLabel(d.operation)}}：{{d.before?previewComponentLabel(d.before):'无'}} → {{d.after?previewComponentLabel(d.after):'无'}}</template><template v-else>目标版本 {{d.target_version_id}} 有未解释的组成差异，未据此拼方。</template></p>
   <p>本次返回组成：<span v-for="(c,index) in item.preview.components||[]" :key="index">{{previewComponentLabel(c)}}；</span></p>
   <details><summary>加减与动作依据</summary><div v-for="row in rows(item,modificationClaimIds(item.preview))" :key="row.id"><p>{{row.id}}：{{row.claim?.text||'来源断言未提供'}}</p><div v-for="a in row.anchors" :key="a.id"><button type="button" class="text-link" @click="open(a)">{{sourceLabel(a)}}</button><small> · {{layerLabel(a.layer)}}</small><blockquote>{{a.quote}}</blockquote></div><p v-if="row.missing" class="warning">动作来源未完整提供。</p></div></details>
  </article>
 </div>
</section>
</template>
<style scoped>
.local-decision{grid-column:1/-1}.local-decision article{margin:10px 0}.local-decision .source-claim{border-top:1px solid #e5e0d6;padding-top:5px}.local-decision blockquote{white-space:pre-wrap;margin:6px 0;padding-left:12px;border-left:3px solid #c8baa1;font-size:12px}.local-decision small{font-size:11px;color:#746b5e}.local-decision details{margin:8px 0}.local-decision summary{cursor:pointer}.local-decision button{white-space:normal;text-align:left}
</style>
