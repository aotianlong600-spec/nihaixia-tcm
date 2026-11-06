import {ApiClient} from './api.ts'

export type AuthMode='api_key'|'codex'
export type ReasoningEffort='auto'|'none'|'minimal'|'low'|'medium'|'high'|'xhigh'|'max'
export const EFFORT_WIRE:ReasoningEffort[]=['none','minimal','low','medium','high','xhigh','max']
export const EFFORT_ALL:ReasoningEffort[]=['auto',...EFFORT_WIRE]
export const EFFORT_LABELS:Record<ReasoningEffort,string>={auto:'模型默认（auto）',none:'关闭思考（none）',minimal:'最少（minimal）',low:'低（low）',medium:'中（medium）',high:'高（high）',xhigh:'超高（xhigh）',max:'最大（max）'}
export function effortLabel(value?:string){return EFFORT_LABELS[(value||'auto') as ReasoningEffort]||`不支持：${value}`}
export interface CodexModel {id:string;name:string;reasoning_efforts?:string[]}
export interface ModelConfig {
 auth_mode:AuthMode;base_url:string;model:string;enabled:boolean;allow_external:boolean;allow_evidence:boolean;reasoning_effort?:string;has_key?:boolean;codex?:any;profile_id?:string|null;profile_name?:string|null
}
export interface Profile {
 id:string;name:string;auth_mode:AuthMode;base_url:string;model:string;enabled:boolean;allow_external:boolean;allow_evidence:boolean;reasoning_effort?:string;has_key:boolean;key_cleanup_incomplete?:boolean
}
const blank=():ModelConfig=>({auth_mode:'api_key',base_url:'',model:'',enabled:false,allow_external:false,allow_evidence:false,reasoning_effort:'auto'})
const normalize=(config:ModelConfig):ModelConfig=>({...config,reasoning_effort:config.reasoning_effort??'auto'})
export class ModelSettingsState {
 config:ModelConfig=blank()
 saved:ModelConfig|null=null
 codex:any={}
 models:CodexModel[]=[]
 catalogNote=''
 profiles:Profile[]=[]
 activeId:string|null=null
 editingId:string|null=null
 name=''
 client:ApiClient
 constructor(client:ApiClient){this.client=client}
 get effortChoices():string[]{
  if(this.config.auth_mode!=='codex')return [...EFFORT_ALL]
  const supported=(this.models.find(m=>m.id===this.config.model)?.reasoning_efforts||[]).filter(v=>EFFORT_WIRE.includes(v as ReasoningEffort))
  return ['auto',...Array.from(new Set(supported))]
 }
 get effortCapabilityKnown(){return this.config.auth_mode!=='codex'||!!this.models.find(m=>m.id===this.config.model&&Array.isArray(m.reasoning_efforts))}
 get effortValid(){return this.effortChoices.includes(this.config.reasoning_effort??'auto')}
 get effortInvalid(){return !this.effortValid}
 get effortNote(){
  if(this.config.auth_mode!=='codex')return 'API Key 渠道需服务商支持 OpenAI reasoning_effort 参数；显式档位可能被拒绝，无法验证任意模型是否支持。'
  if(!this.effortCapabilityKnown)return '未知或自定义 Codex 模型未声明思考档位能力，仅可使用“自动”（不发送覆盖）。'
  return '仅显示该 Codex 模型目录声明的受支持档位。'
 }
 private assertEffort(){
  const value=this.config.reasoning_effort??'auto'
  if(!EFFORT_ALL.includes(value as ReasoningEffort))throw Error('请选择有效的思考档位')
  if(!this.effortChoices.includes(value))throw Error('所选思考档位不受当前模型支持，请改为“自动”或受支持档位后再保存')
  this.config.reasoning_effort=value
 }
 modelChanged(){if(!this.effortValid)this.config.reasoning_effort='auto'}
 private applySaved(config:ModelConfig){
  this.config=normalize(config);this.codex=config.codex||{}
  if('profile_id'in config){this.activeId=config.profile_id??null;this.saved=config.profile_id?normalize(config):null}
  else this.saved=normalize(config)
 }
 private fields(){const {auth_mode,base_url,model,enabled,allow_external,allow_evidence,reasoning_effort}=this.config;return {auth_mode,base_url:auth_mode==='codex'?'':base_url,model,enabled,allow_external,allow_evidence,reasoning_effort:reasoning_effort??'auto'}}
 async load(){this.applySaved(await this.client.request<ModelConfig>('/model/config'));if(this.config.auth_mode==='codex')await this.loadModels()}
 async save(key=''){
  const {auth_mode}=this.config
  this.assertEffort()
  this.applySaved(await this.client.put<ModelConfig>('/model/config',{...this.fields(),...(auth_mode==='api_key'&&key?{api_key:key}:{})}))
 }
 async loadProfiles(){const result=await this.client.request<{items:Profile[];active_id:string|null}>('/model/profiles');this.profiles=result.items;this.activeId=result.active_id;return result}
 selectForEdit(profile:Profile){this.editingId=profile.id;this.name=profile.name;this.config=normalize({auth_mode:profile.auth_mode,base_url:profile.base_url,model:profile.model,enabled:profile.enabled,allow_external:profile.allow_external,allow_evidence:profile.allow_evidence,reasoning_effort:profile.reasoning_effort,has_key:profile.has_key})}
 newDraft(){this.editingId=null;this.name='';this.config=blank()}
 async saveProfile(key=''){
  const name=this.name.trim()
  if(!name)throw Error('请填写配置名称')
  if(name.length>80)throw Error('配置名称最多80字符')
  this.assertEffort()
  const payload={name,...this.fields(),...(this.config.auth_mode==='api_key'&&key?{api_key:key}:{})}
  const profile=this.editingId?await this.client.put<Profile>(`/model/profiles/${encodeURIComponent(this.editingId)}`,payload):await this.client.post<Profile>('/model/profiles',payload)
  const saved=normalize({auth_mode:profile.auth_mode,base_url:profile.base_url,model:profile.model,enabled:profile.enabled,allow_external:profile.allow_external,allow_evidence:profile.allow_evidence,reasoning_effort:profile.reasoning_effort,has_key:profile.has_key})
  this.config=saved;this.editingId=profile.id;this.name=profile.name
  if(profile.id===this.activeId)this.saved={...saved,profile_id:profile.id,profile_name:profile.name}
  this.profiles=this.profiles.some(p=>p.id===profile.id)?this.profiles.map(p=>p.id===profile.id?profile:p):[...this.profiles,profile]
  return profile
 }
 async useProfile(id:string){
  const active=await this.client.post<ModelConfig>(`/model/profiles/${encodeURIComponent(id)}/select`,{})
  this.saved=normalize(active);this.activeId=active.profile_id??id;if(active.codex)this.codex=active.codex
  return active
 }
 async deleteProfile(id:string){
  const result=await this.client.request<{deleted_id:string;active_id:string|null;key_cleanup_incomplete?:boolean}>(`/model/profiles/${encodeURIComponent(id)}`,{method:'DELETE'})
  const wasEditing=this.editingId===result.deleted_id
  this.profiles=this.profiles.filter(p=>p.id!==result.deleted_id);this.activeId=result.active_id
  if(result.active_id===null||result.deleted_id===this.saved?.profile_id)this.saved=null
  if(wasEditing)this.newDraft()
  return result
 }
 async refreshCodex(){this.codex=await this.client.request('/model/codex')}
 async submitLoginCode(value:string){
  const id=this.codex.login?.id
  if(!id)throw Error('当前没有等待完成的Codex授权')
  await this.client.post(`/model/codex/login/${encodeURIComponent(id)}/code`,{value})
  await this.refreshCodex()
 }
 async selectAuthMode(mode:AuthMode){this.config.auth_mode=mode;if(mode==='codex')await this.loadModels();this.modelChanged()}
 async loadModels(){const result=await this.client.request<{items:CodexModel[];scope:string}>('/model/codex/models');this.models=result.items;this.catalogNote=result.scope}
}
