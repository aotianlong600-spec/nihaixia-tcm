<script setup lang="ts">
import {computed,onUnmounted,reactive,ref,toRefs,watch} from 'vue'
import {api} from './api'
import {ModelSettingsState,effortLabel} from './modelSettingsState'
import type {ConsultationSelection} from './modelSettingsState'
const props=defineProps<{active:boolean;disabled:boolean}>()
const emit=defineEmits<{(e:'ready',selection:ConsultationSelection|null):void;(e:'settings'):void}>()
const state=reactive(new ModelSettingsState(api))
const {config,saved,profiles,editingId,models}=toRefs(state)
const loading=ref(true), applying=ref(false), error=ref(''), notice=ref('')
let requestId=0, disposed=false
const busy=computed(()=>loading.value||applying.value||props.disabled)
const pending=computed(()=>!!editingId.value&&(state.consultationDirty||editingId.value!==saved.value?.profile_id))
const selection=computed<ConsultationSelection|null>(()=>props.active&&!props.disabled&&!loading.value&&!applying.value&&!error.value&&!state.consultationDirty?state.consultationSelection:null)
const readinessNote=computed(()=>{
 const current=saved.value
 if(!current)return '当前没有生效的模型配置，请在“模型设置”中创建、启用并设为当前；问诊不会自动改用其他配置。'
 if(!current.model)return '当前生效配置尚未设置模型。'
 if(!current.enabled)return '当前生效配置未启用模型服务。'
 if(!current.allow_external||!current.allow_evidence)return '当前配置未允许发送必要症状与书证。'
 if(current.auth_mode==='api_key'&&!current.has_key)return '当前配置缺少API密钥。'
 if(current.auth_mode==='codex'&&!state.codex?.logged_in)return 'Codex账号尚未完成授权。'
 if(typeof current.profile_revision!=='number')return '服务未返回已保存的配置版本，暂不可发送；请刷新后重试。'
 if(!state.savedEffortValid)return '当前生效配置的思考档位不受所选模型支持，请改为“自动”或受支持档位。'
 return ''
})
function message(value:unknown){return value instanceof Error?value.message:String(value)}
watch(selection,value=>emit('ready',value),{immediate:true})
watch(()=>props.active,value=>{
 if(!value)return
 void load()
},{immediate:true})
function editProfile(event:Event){
 const id=(event.target as HTMLSelectElement).value
 const profile=profiles.value.find(p=>p.id===id)
 notice.value=''
 if(!profile){state.newDraft();return}
 state.selectForEdit(profile)
 if(profile.auth_mode==='codex'&&!models.value.length)void loadCatalog()
}
function modelChanged(){state.modelChanged();notice.value=''}
function effortChanged(){notice.value=''}
async function loadCatalog(){
 loading.value=true
 try{await state.loadModels();error.value=''}catch(e){error.value=message(e)}finally{loading.value=false}
}
async function load(){
 const id=++requestId
 loading.value=true;error.value='';notice.value=''
 try{await state.loadConsultation()}catch(e){if(id===requestId&&!disposed)error.value=message(e)}finally{if(id===requestId&&!disposed)loading.value=false}
}
async function refresh(){
 if(busy.value||applying.value)return
 if(state.consultationDirty&&!confirm('放弃未应用的修改并重新载入当前配置？'))return
 await load()
}
async function apply(){
 if(!props.active||busy.value||applying.value)return
 applying.value=true;error.value='';notice.value=''
 try{
  await state.applyConsultation()
  if(!disposed){
   if(state.consultationSelection)notice.value='已应用，新的模型请求将使用该配置。'
   else error.value='配置已设为当前，但尚不满足发送条件；请按提示补全模型设置或刷新。'
  }
 }catch(e){if(!disposed)error.value=message(e)}finally{if(!disposed)applying.value=false}
}
onUnmounted(()=>{disposed=true;requestId++;emit('ready',null)})
</script>
<template>
<section v-if="props.active" class="consult-model-bar" aria-label="问诊模型配置">
 <div class="bar-head">
  <h2>问诊模型配置</h2>
  <span v-if="pending" class="draft-badge">待应用</span>
  <span v-else-if="saved&&selection" class="applied-badge">已应用</span>
  <button type="button" class="text-link" @click="emit('settings')">模型设置</button>
 </div>
 <p v-if="loading" class="hint" role="status">正在加载问诊模型配置……</p>
 <template v-else>
  <div class="effective" aria-label="当前生效的模型配置">
   <p v-if="saved"><strong>{{saved.profile_name||'（未命名配置）'}}</strong> · {{saved.auth_mode==='codex'?'Codex账号授权':'API Key'}} · 模型：{{saved.model||'未设置'}} · 思考档位：{{effortLabel(saved.reasoning_effort)}} · {{saved.enabled?'已启用':'未启用'}}</p>
   <p v-else class="hint">当前没有生效的模型配置，请在“模型设置”中创建并启用；不会自动改用其他配置。</p>
  </div>
  <div v-if="profiles.length" class="model-grid">
   <label>问诊模型配置<select :value="editingId||''" :disabled="busy" aria-label="问诊模型配置" @change="editProfile">
    <option value="">请选择已保存配置</option>
    <option v-for="p in profiles" :key="p.id" :value="p.id">{{p.name}} · {{p.auth_mode==='codex'?'Codex':'API Key'}} · {{p.model||'未设置模型'}}{{p.id===saved?.profile_id?'（当前生效）':''}}</option>
   </select></label>
   <template v-if="editingId">
    <label v-if="config.auth_mode==='codex'">问诊模型<select v-model="config.model" :disabled="busy" aria-label="问诊模型" @change="modelChanged">
     <option value="">请选择模型</option>
     <option v-if="config.model&&!models.some(m=>m.id===config.model)" :value="config.model">自定义：{{config.model}}</option>
     <option v-for="m in models" :key="m.id" :value="m.id">{{m.name}} · {{m.id}}</option>
    </select></label>
    <label v-else>问诊模型<input v-model="config.model" :disabled="busy" autocomplete="off" maxlength="200" placeholder="模型 ID" aria-label="问诊模型" @input="modelChanged"></label>
    <label>问诊思考档位<select v-model="config.reasoning_effort" :disabled="busy" aria-label="问诊思考档位" @change="effortChanged">
     <option v-if="state.effortInvalid" :value="config.reasoning_effort">不受支持：{{config.reasoning_effort}}</option>
     <option v-for="e in state.effortChoices" :key="e" :value="e">{{effortLabel(e)}}</option>
    </select></label>
    <div class="bar-actions">
     <button type="button" class="primary" :disabled="busy||!config.model" @click="apply">应用</button>
     <button type="button" :disabled="busy" @click="refresh">刷新</button>
    </div>
   </template>
  </div>
  <p v-else class="hint">尚未保存任何模型配置，请先前往“模型设置”创建配置。</p>
  <p v-if="editingId" class="hint">{{state.effortNote}}</p>
  <p v-if="pending" class="hint">选择仅作为草稿，点击“应用”后新的模型请求才会使用。</p>
  <p v-if="readinessNote" class="hint">{{readinessNote}} <button type="button" class="text-link" @click="emit('settings')">前往模型设置</button></p>
  <p v-if="error" class="error-box" role="alert">{{error}}</p>
  <p v-if="notice" class="notice" role="status">{{notice}}</p>
 </template>
</section>
</template>
<style scoped>
.consult-model-bar{border:1px solid #e7dfcf;border-radius:10px;background:#fffefa;padding:12px 14px;margin:0 0 10px;font-size:12px}
.bar-head{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.bar-head h2{font-family:serif;font-size:15px;margin:0;color:#6b5330;letter-spacing:1px}
.bar-head .text-link{margin-left:auto;font-size:12px}
.draft-badge,.applied-badge{font-size:11px;padding:1px 7px;border-radius:10px}
.draft-badge{background:#f3e7c8;color:#7a5a1e;border:1px solid #ddc38c}
.applied-badge{background:#e8f0e3;color:#3e6347;border:1px solid #c4d6bd}
.effective p{margin:6px 0 0;color:#5d5444}
.effective p.hint{margin-top:4px}
.model-grid{display:grid;grid-template-columns:minmax(180px,1.15fr) minmax(150px,1fr) minmax(140px,1fr) auto;gap:10px;align-items:end;margin-top:8px}
.model-grid label{margin:0;font-size:11px;display:flex;flex-direction:column;gap:3px}
.model-grid select,.model-grid input{margin-top:0;padding:6px 8px}
.bar-actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.bar-actions button{min-height:32px;white-space:nowrap}
.consult-model-bar .error-box,.consult-model-bar .notice{margin:8px 0 0;padding:7px 9px}
@media(max-width:850px){.model-grid{grid-template-columns:1fr 1fr}.bar-actions{justify-content:flex-end}}
@media(max-width:560px){.model-grid{grid-template-columns:1fr}.bar-actions button{flex:1}}
</style>
