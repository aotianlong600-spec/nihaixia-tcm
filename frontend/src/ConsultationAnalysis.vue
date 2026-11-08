<script setup lang="ts">
import {computed} from 'vue'
import LocalDecision from './LocalDecision.vue'
import {locatorLabel,actionLabel} from './personalState'

const props=defineProps<{analysis:any;graph?:any;evidence?:any[];revision?:number}>()
const emit=defineEmits<{(e:'source',value:{source:string;unit:number}):void;(e:'formula',id:string):void;(e:'fact',value:{term:string;state:'present'|'absent'}):void}>()

const list=(value:any):any[]=>Array.isArray(value)?value:[]
const map=(value:any):Record<string,string>=>value&&typeof value==='object'?value:{}
const present=computed(()=>list(props.analysis?.present))
const absent=computed(()=>list(props.analysis?.absent))
const conflicts=computed(()=>list(props.analysis?.conflicts))
const unknown=computed(()=>list(props.analysis?.unknown))
const unverified=computed(()=>[...new Set([...list(props.analysis?.unverified_terms),...list(props.analysis?.retrieval_terms),...list(props.analysis?.raw_retrieval)])].filter(term=>!present.value.includes(term)&&!absent.value.includes(term)))
const checkable=computed(()=>[...new Set([...unverified.value,...unknown.value,...conflicts.value])])
const presentLabels=computed(()=>map(props.analysis?.present_labels))
const absentLabels=computed(()=>map(props.analysis?.absent_labels))
const items=computed(()=>list(props.analysis?.items))

function label(term:any,labels:Record<string,string>){return labels[term]||String(term)}
function labeled(values:any[],labels:Record<string,string>){return values.map(term=>label(term,labels)).join('、')||'未提供'}
function terms(values:any){return list(values).map(value=>String(value)).join('、')||'未提供'}
function matchedText(item:any){const labels=map(item?.matched_labels);return list(item?.matched_terms).map((term:any)=>label(term,labels)).join('、')||'未提供'}

function canOpen(source:any){return source?.source_id!=null&&source.source_id!==''&&source?.unit_no!=null&&source.unit_no!==''&&Number.isFinite(Number(source.unit_no))}
function emitSource(source:any){if(canOpen(source))emit('source',{source:String(source.source_id),unit:Number(source.unit_no)})}
function openFormula(item:any){if(item?.formula_id!=null&&item.formula_id!=='')emit('formula',String(item.formula_id))}
function forwardSource(value:{source:string;unit:number}){emit('source',value)}

function sourceTitle(source:any){
 const title=source?.source_title||source?.title
 if(title)return String(title)
 return source?.source_id!=null&&source.source_id!==''?String(source.source_id):'来源未提供'
}
function sourceLocation(source:any){
 const locator=source?.locator
 const rendered=typeof locator==='string'?locator:locator?locatorLabel({locator}):''
 if(rendered&&rendered!=='位置未提供')return rendered
 return source?.unit_no!=null&&source.unit_no!==''?`单元 ${source.unit_no}`:'位置未提供'
}
function quoteTitle(entry:any){return entry?.quote_sha256?`引文SHA256：${entry.quote_sha256}`:undefined}

function doseText(component:any){
 const dose=component?.source_dose
 return dose==null||dose===''?'未提供':`${dose}${component?.source_unit||''}`
}
function componentLabel(component:any){
 const processing=component?.processing?`（${component.processing}）`:''
 return `${component?.name||'药名未提供'}${processing} · 来源原量 ${doseText(component)}`
}
function versionName(version:any,index:number){
 const id=version?.id
 return id!=null&&id!==''?`版本 ${id}`:`版本 ${index+1}`
}
function versionSource(version:any){
 const source=version?.source
 if(source==null||source==='')return ''
 if(typeof source==='string'||typeof source==='number')return String(source)
 return sourceTitle(source)
}
function actionDose(action:any){
 const dose=action?.dose
 return dose==null||dose===''?'剂量未提供':`${dose}${action?.unit||''}`
}
function actionText(action:any){
 const verb=action?.action?actionLabel(action.action):'动作未提供'
 return `${verb} ${action?.herb||'药名未提供'} · ${actionDose(action)}`
}
</script>
<template>
<div class="consultation-analysis">
 <section class="panel analysis-panel" aria-label="库内方证分析">
  <div class="analysis-head"><h2>库内方证分析</h2><span v-if="revision!=null" class="hint">记录版本 {{revision}}</span></div>
  <div class="analysis-facts">
   <div class="fact-group" data-fact-group="confirmed">
    <h3>已确认输入</h3>
    <p v-if="present.length"><strong>已确认存在</strong>：{{labeled(present,presentLabels)}}</p>
    <p v-if="absent.length"><strong>已确认否认</strong>：{{labeled(absent,absentLabels)}}</p>
    <p v-if="!present.length&&!absent.length" class="hint">暂无已确认输入。</p>
   </div>
   <div v-if="conflicts.length" class="fact-group" data-fact-group="conflicts">
    <h3 class="warning">冲突</h3><p class="warning">{{terms(conflicts)}}</p>
   </div>
   <div v-if="unknown.length" class="fact-group" data-fact-group="unknown">
    <h3>未知</h3><p>{{terms(unknown)}}</p>
   </div>
   <div v-if="unverified.length" class="fact-group" data-fact-group="unverified">
    <h3>未核验词面线索</h3>
    <p class="hint">以下词面线索未确立为患者事实，仅用于检索：{{terms(unverified)}}</p>
   </div>
  </div>
  <section v-if="checkable.length"><h3>核对当前体征</h3><div v-for="term in checkable" :key="term" class="button-row"><span>{{term}}</span><button type="button" @click="emit('fact',{term:String(term),state:'present'})">核对为当前存在</button><button type="button" @click="emit('fact',{term:String(term),state:'absent'})">核对为当前否认</button></div></section>
  <section v-if="items.length" class="analysis-candidates" aria-label="候选方证">
   <h3>候选方证</h3>
   <article v-for="(item,index) in items" :key="item?.formula_id||index" class="result-card analysis-item" :data-formula-id="item?.formula_id">
    <div class="candidate-head">
     <h4>{{item?.formula_name||item?.formula_id||'方剂未提供'}}</h4>
     <button v-if="item?.formula_id!=null&&item.formula_id!==''" type="button" class="text-link" @click="openFormula(item)">查看方剂</button>
    </div>
    <p class="hint">检索排序分 {{item?.score ?? '未提供'}} · 仅用于库内检索排序<template v-if="item?.syndrome"> · {{item.syndrome}}</template></p>
    <p><strong>支持线索</strong>：{{matchedText(item)}}</p>
    <p v-if="list(item?.matched_raw_terms).length"><strong>词面命中（未核验）</strong>：{{terms(item?.matched_raw_terms)}}</p>
    <p><strong>原文提及、待核对</strong>：{{terms(item?.missing_terms)}}</p>
    <p :class="{warning:list(item?.contradicted_terms).length}"><strong>反证</strong>：{{terms(item?.contradicted_terms)}}</p>
    <div v-if="list(item?.evidence).length" class="analysis-evidence">
     <h4>原文摘录</h4>
     <div v-for="(entry,entryIndex) in list(item?.evidence)" :key="entryIndex" class="evidence-item">
      <button v-if="canOpen(entry)" type="button" class="text-link" @click="emitSource(entry)">{{sourceTitle(entry)}} · {{sourceLocation(entry)}}</button>
      <span v-else class="hint">{{sourceTitle(entry)}} · {{sourceLocation(entry)}}</span>
      <blockquote :title="quoteTitle(entry)">{{entry?.quote||'引文未提供'}}</blockquote>
     </div>
    </div>
    <details v-if="list(item?.composition_versions).length" class="analysis-compositions">
     <summary>来源组成版本（{{list(item?.composition_versions).length}} 个，独立展示）</summary>
     <p class="hint">按版本分别展示来源原量，不跨版本拼合；来源原量非个人日量。</p>
     <article v-for="(version,versionIndex) in list(item?.composition_versions)" :key="versionIndex" class="composition-version" :data-composition-version="version?.id ?? versionIndex">
      <h4>{{versionName(version,versionIndex)}}<template v-if="versionSource(version)"> · {{versionSource(version)}}</template></h4>
      <p v-for="(component,componentIndex) in list(version?.components)" :key="componentIndex">{{componentLabel(component)}}</p>
      <p v-if="!list(version?.components).length" class="hint">组成未提供。</p>
      <details v-if="version?.raw_block"><summary>原文组成</summary><pre>{{version.raw_block}}</pre></details>
     </article>
    </details>
    <section v-if="list(item?.modifications).length" class="analysis-modifications">
     <h4>原文加减线索</h4>
     <p class="hint">逐条展示原文条件、动作与出处；本组件不据此调整组成。</p>
     <article v-for="(modification,modificationIndex) in list(item?.modifications)" :key="modificationIndex" class="modification" :data-modification-index="modificationIndex">
      <p><strong>{{modification?.condition||'条件未提供'}}</strong></p>
      <p v-if="modification?.raw">{{modification.raw}}</p>
      <ul v-if="list(modification?.actions).length">
       <li v-for="(action,actionIndex) in list(modification?.actions)" :key="actionIndex">{{actionText(action)}}</li>
      </ul>
      <p v-else class="hint">动作未提供。</p>
      <button v-if="canOpen(modification?.source)" type="button" class="text-link" @click="emitSource(modification.source)">{{sourceTitle(modification.source)}} · {{sourceLocation(modification.source)}}</button>
      <span v-else-if="modification?.source" class="hint">{{sourceTitle(modification.source)}} · {{sourceLocation(modification.source)}}</span>
      <p v-if="modification?.reason" class="hint">原文说明：{{modification.reason}}</p>
     </article>
    </section>
   </article>
  </section>
  <p v-else class="hint">本次分析没有候选方证。</p>
 </section>
 <LocalDecision v-if="graph" :graph="graph" :evidence="evidence" :revision="revision" @source="forwardSource"/>
</div>
</template>
<style scoped>
.consultation-analysis{display:grid;gap:14px}.consultation-analysis .analysis-panel{margin:0}.analysis-head{display:flex;justify-content:space-between;align-items:baseline;gap:10px;flex-wrap:wrap}.analysis-head h2{margin:0}.analysis-facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px;margin-top:12px}.fact-group{border-top:1px solid #e7dfcf;padding-top:8px;min-width:0}.fact-group h3{margin-bottom:4px}.analysis-candidates{margin-top:14px}.analysis-item{margin:12px 0;padding:14px}.candidate-head{display:flex;justify-content:space-between;align-items:baseline;gap:10px}.candidate-head h4{margin:0}.analysis-item p{margin:5px 0}.evidence-item,.composition-version,.modification{border-top:1px solid #ece4d6;padding-top:8px;margin-top:8px}.evidence-item blockquote{white-space:pre-wrap;margin:6px 0;padding-left:12px;border-left:3px solid #c8baa1;font-size:12px}.composition-version h4{margin:0 0 4px}.analysis-modifications ul{margin:4px 0;padding-left:20px}.analysis-modifications li{font-size:12px;margin:3px 0}@media(max-width:600px){.analysis-facts{grid-template-columns:1fr}.candidate-head{display:block}}
</style>
