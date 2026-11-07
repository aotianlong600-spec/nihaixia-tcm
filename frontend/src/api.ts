export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) { super(message); this.status = status }
}
interface NativeBridge {request:(id:string,method:string,path:string,body:string)=>void}
declare global {interface Window {NihaixiaLocal?:NativeBridge}}
type PendingNative={path:string;resolve:(value:any)=>void;reject:(error:ApiError)=>void;timer:ReturnType<typeof setTimeout>}
export class ApiClient {
  base: string
  token = ''
  runtime={platform:'desktop',standalone:false}
  onUnauthorized?: () => void
  private pending=new Map<string,PendingNative>()
  private surface?:Window
  private nativeSeen=false
  constructor(base = '') {
    this.base = base
    if(typeof window!=='undefined'&&(typeof window.NihaixiaLocal?.request==='function'||window.location?.origin==='https://appassets.androidplatform.net')){this.nativeSeen=true;this.runtime={platform:'android',standalone:true}}
  }
  private bridge(){
    const bridge=typeof window!=='undefined'?window.NihaixiaLocal:undefined
    if(typeof bridge?.request==='function'){this.nativeSeen=true;this.runtime={platform:'android',standalone:true};return bridge}
    if(this.nativeSeen)throw new ApiError(0,'设备本地接口不可用，请重新打开应用')
    return null
  }
  private finishNative(id:string,value:any,error?:ApiError){
    const pending=this.pending.get(id)
    if(!pending)return
    this.pending.delete(id);clearTimeout(pending.timer)
    if(!this.pending.size&&this.surface){
      this.surface.removeEventListener('nihaixia-local-response',this.receiveNative)
      this.surface.removeEventListener('pagehide',this.closeNative)
      this.surface=undefined
    }
    if(error)pending.reject(error);else pending.resolve(value)
  }
  private receiveNative=(event:Event)=>{
    const result=(event as CustomEvent).detail
    if(!result||typeof result.id!=='string'||!this.pending.has(result.id))return
    const invalid=()=>this.finishNative(result.id,null,new ApiError(502,'设备本地响应格式无效'))
    if(!Number.isInteger(result.status)||result.status<100||result.status>599){invalid();return}
    if(result.status<200||result.status>=300){
      if(result.status===401&&this.pending.get(result.id)?.path!=='/access/login')this.onUnauthorized?.()
      const detail=result.body?.detail
      this.finishNative(result.id,null,new ApiError(result.status,typeof detail==='string'?detail:`本地请求失败（${result.status}）`));return
    }
    if(result.base64!==undefined){
      if(typeof result.base64!=='string'||result.base64.length>32*1024*1024||
         (result.content_type!==undefined&&typeof result.content_type!=='string')){invalid();return}
      try{
        const bytes=Uint8Array.from(atob(result.base64),char=>char.charCodeAt(0))
        this.finishNative(result.id,new Blob([bytes],{type:result.content_type||'application/octet-stream'}))
      }catch{invalid()}
    }else this.finishNative(result.id,result.body)
  }
  private closeNative=()=>this.dispose()
  dispose(){
    for(const id of this.pending.keys())this.finishNative(id,null,new ApiError(0,'设备本地请求已取消'))
  }
  private nativeRequest(bridge:NativeBridge,method:string,path:string,body?:BodyInit|null){
    if(!/^\/(?!\/)[^\\\x00-\x20\x7f#]*$/.test(path)||!['GET','HEAD','POST','PUT','PATCH','DELETE'].includes(method))return Promise.reject(new ApiError(400,'设备本地请求格式无效'))
    if(body!=null&&typeof body!=='string')return Promise.reject(new ApiError(400,'设备本地接口只接收JSON文本'))
    if(this.pending.size>=64)return Promise.reject(new ApiError(429,'设备本地请求过多，请稍后重试'))
    const id=crypto.randomUUID()
    return new Promise<any>((resolve,reject)=>{
      if(!this.surface){
        this.surface=window
        this.surface.addEventListener('nihaixia-local-response',this.receiveNative)
        this.surface.addEventListener('pagehide',this.closeNative)
      }
      const timer=setTimeout(()=>this.finishNative(id,null,new ApiError(0,'设备本地请求超时，请重试')),30000)
      this.pending.set(id,{path,resolve,reject,timer})
      // Only the native bridge receives the body; keys never enter URLs or a fetch fallback.
      try{bridge.request(id,method,path,body??'')}catch{this.finishNative(id,null,new ApiError(0,'设备本地请求未能提交，请重试'))}
    })
  }
  async session() {
    const bridge=this.bridge()
    if(bridge){
      const session=await this.nativeRequest(bridge,'GET','/session')
      if(!session||session.authenticated!==true||session.platform!=='android'||session.standalone!==true||typeof session.csrf_token!=='string')throw new ApiError(502,'设备本地会话格式无效')
      this.token=session.csrf_token;return session
    }
    const response = await fetch(`${this.base}/api/session`, {credentials:'same-origin'})
    if (!response.ok) throw new ApiError(response.status, '会话初始化失败')
    const session = await response.json()
    this.token = session.csrf_token
    this.runtime={platform:typeof session.platform==='string'?session.platform:'desktop',standalone:session.standalone===true}
    return session
  }
  async request<T = any>(path: string, options: RequestInit = {}): Promise<T> {
    const bridge=this.bridge()
    if(bridge)return this.nativeRequest(bridge,(options.method||'GET').toUpperCase(),path,options.body)
    if (!this.token) await this.session()
    const headers = new Headers(options.headers)
    if (options.method && !['GET','HEAD'].includes(options.method.toUpperCase())) headers.set('X-CSRF-Token', this.token)
    if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json')
    const response = await fetch(`${this.base}/api${path}`, {...options, headers, credentials:'same-origin'})
    if (!response.ok) {
      if (response.status === 401 && path !== '/access/login') this.onUnauthorized?.()
      const problem = await response.json().catch(() => ({detail:response.statusText}))
      throw new ApiError(response.status, typeof problem.detail === 'string' ? problem.detail : JSON.stringify(problem.detail))
    }
    if (response.headers.get('content-type')?.includes('application/json')) return response.json()
    return await response.blob() as T
  }
  post<T = any>(path: string, data: unknown): Promise<T> { return this.request(path,{method:'POST',body:JSON.stringify(data)}) }
  put<T = any>(path: string, data: unknown): Promise<T> { return this.request(path,{method:'PUT',body:JSON.stringify(data)}) }
}
export const api = new ApiClient()
