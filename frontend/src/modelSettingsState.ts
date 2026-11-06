import {ApiClient} from './api.ts'

type AuthMode='api_key'|'codex'
interface ModelConfig {
 auth_mode:AuthMode;base_url:string;model:string;enabled:boolean;allow_external:boolean;allow_evidence:boolean;has_key?:boolean;codex?:any
}
export class ModelSettingsState {
 config:ModelConfig={auth_mode:'api_key',base_url:'',model:'',enabled:false,allow_external:false,allow_evidence:false}
 saved:ModelConfig|null=null
 codex:any={}
 models:{id:string;name:string}[]=[]
 catalogNote=''
 client:ApiClient
 constructor(client:ApiClient){this.client=client}
 private applySaved(config:ModelConfig){this.saved={...config};this.config={...config};this.codex=config.codex||{}}
 async load(){this.applySaved(await this.client.request<ModelConfig>('/model/config'));if(this.config.auth_mode==='codex')await this.loadModels()}
 async save(key=''){
  const {auth_mode,base_url,model,enabled,allow_external,allow_evidence}=this.config
  this.applySaved(await this.client.put<ModelConfig>('/model/config',{auth_mode,base_url:auth_mode==='codex'?'':base_url,model,enabled,allow_external,allow_evidence,...(auth_mode==='api_key'&&key?{api_key:key}:{})}))
 }
 async refreshCodex(){this.codex=await this.client.request('/model/codex')}
 async selectAuthMode(mode:AuthMode){this.config.auth_mode=mode;if(mode==='codex')await this.loadModels()}
 async loadModels(){const result=await this.client.request<{items:{id:string;name:string}[];scope:string}>('/model/codex/models');this.models=result.items;this.catalogNote=result.scope}
}
