import {ApiClient} from './api.ts'

export type AuthMode='api_key'|'codex'
export interface ModelConfig {
 auth_mode:AuthMode;base_url:string;model:string;enabled:boolean;allow_external:boolean;allow_evidence:boolean;has_key?:boolean;codex?:any;profile_id?:string|null;profile_name?:string|null
}
export interface Profile {
 id:string;name:string;auth_mode:AuthMode;base_url:string;model:string;enabled:boolean;allow_external:boolean;allow_evidence:boolean;has_key:boolean;key_cleanup_incomplete?:boolean
}
const blank=():ModelConfig=>({auth_mode:'api_key',base_url:'',model:'',enabled:false,allow_external:false,allow_evidence:false})
export class ModelSettingsState {
 config:ModelConfig=blank()
 saved:ModelConfig|null=null
 codex:any={}
 models:{id:string;name:string}[]=[]
 catalogNote=''
 profiles:Profile[]=[]
 activeId:string|null=null
 editingId:string|null=null
 name=''
 client:ApiClient
 constructor(client:ApiClient){this.client=client}
 private applySaved(config:ModelConfig){
  this.config={...config};this.codex=config.codex||{}
  if('profile_id'in config){this.activeId=config.profile_id??null;this.saved=config.profile_id?{...config}:null}
  else this.saved={...config}
 }
 private fields(){const {auth_mode,base_url,model,enabled,allow_external,allow_evidence}=this.config;return {auth_mode,base_url:auth_mode==='codex'?'':base_url,model,enabled,allow_external,allow_evidence}}
 async load(){this.applySaved(await this.client.request<ModelConfig>('/model/config'));if(this.config.auth_mode==='codex')await this.loadModels()}
 async save(key=''){
  const {auth_mode}=this.config
  this.applySaved(await this.client.put<ModelConfig>('/model/config',{...this.fields(),...(auth_mode==='api_key'&&key?{api_key:key}:{})}))
 }
 async loadProfiles(){const result=await this.client.request<{items:Profile[];active_id:string|null}>('/model/profiles');this.profiles=result.items;this.activeId=result.active_id;return result}
 selectForEdit(profile:Profile){this.editingId=profile.id;this.name=profile.name;this.config={auth_mode:profile.auth_mode,base_url:profile.base_url,model:profile.model,enabled:profile.enabled,allow_external:profile.allow_external,allow_evidence:profile.allow_evidence,has_key:profile.has_key}}
 newDraft(){this.editingId=null;this.name='';this.config=blank()}
 async saveProfile(key=''){
  const name=this.name.trim()
  if(!name)throw Error('请填写配置名称')
  if(name.length>80)throw Error('配置名称最多80字符')
  const payload={name,...this.fields(),...(this.config.auth_mode==='api_key'&&key?{api_key:key}:{})}
  const profile=this.editingId?await this.client.put<Profile>(`/model/profiles/${encodeURIComponent(this.editingId)}`,payload):await this.client.post<Profile>('/model/profiles',payload)
  const saved={auth_mode:profile.auth_mode,base_url:profile.base_url,model:profile.model,enabled:profile.enabled,allow_external:profile.allow_external,allow_evidence:profile.allow_evidence,has_key:profile.has_key}
  this.config=saved;this.editingId=profile.id;this.name=profile.name
  if(profile.id===this.activeId)this.saved={...saved,profile_id:profile.id,profile_name:profile.name}
  this.profiles=this.profiles.some(p=>p.id===profile.id)?this.profiles.map(p=>p.id===profile.id?profile:p):[...this.profiles,profile]
  return profile
 }
 async useProfile(id:string){
  const active=await this.client.post<ModelConfig>(`/model/profiles/${encodeURIComponent(id)}/select`,{})
  this.saved={...active};this.activeId=active.profile_id??id;if(active.codex)this.codex=active.codex
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
 async selectAuthMode(mode:AuthMode){this.config.auth_mode=mode;if(mode==='codex')await this.loadModels()}
 async loadModels(){const result=await this.client.request<{items:{id:string;name:string}[];scope:string}>('/model/codex/models');this.models=result.items;this.catalogNote=result.scope}
}
