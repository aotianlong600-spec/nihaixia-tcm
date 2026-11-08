import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {createRequire} from 'node:module'
import {parse, compileScript} from '@vue/compiler-sfc'
import {createSSRApp} from 'vue'
import * as vue from 'vue'
import {renderToString} from '@vue/server-renderer'
import {setImmediate} from 'node:timers/promises'
import ts from 'typescript'

const require = createRequire(import.meta.url)
const browserApi = {runtime:{platform:'browser',standalone:true}}
const placeholder = {template:'<div></div>'}

function component(name:string, imports:Record<string,unknown>) {
  const source = readFileSync(new URL(`../src/${name}.vue`,import.meta.url),'utf8')
  const {descriptor} = parse(source)
  const compiled = compileScript(descriptor,{id:name,inlineTemplate:true})
  const output = ts.transpileModule(compiled.content,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText
  const module = {exports:{} as any}
  new Function('require','module','exports',output)((name:string)=>name in imports?imports[name]:require(name),module,module.exports)
  return module.exports.default
}

test('browser app keeps model settings, model selection and AI send controls available',async()=>{
  const descriptor = Object.getOwnPropertyDescriptor(globalThis,'window')
  Object.defineProperty(globalThis,'window',{configurable:true,value:new EventTarget()})
  const app = component('App',{
    'vue':{...vue,onMounted:(callback:()=>void)=>vue.onServerPrefetch(async()=>{callback();await setImmediate()})},
    './api':{api:{...browserApi,session:async()=>({authenticated:true,standalone:true}),request:async()=>({items:[]})},ApiError:Error},
    './personalState':{},
    './Settings.vue':{default:placeholder},
    './ConsultModelBar.vue':{default:{template:'<div data-model-bar="true"></div>'}},
    './LocalDecision.vue':{default:placeholder},
  })
  try {
    const instance = createSSRApp(app)
    instance.component('el-dialog',placeholder)
    const html = await renderToString(instance)
    assert.match(html,/模型与数据/)
    assert.match(html,/<nav>.*倪氏书库.*<\/nav>/s)
    assert.match(html,/data-model-bar="true"/)
    assert.match(html,/<textarea/)
    assert.match(html,/发送并请求 AI/)
    assert.doesNotMatch(html,/云模型可在本机版使用/)
  } finally {
    if(descriptor)Object.defineProperty(globalThis,'window',descriptor)
    else delete (globalThis as any).window
  }
})

test('browser settings describe browser credentials and expose only device-code Codex login',async()=>{
  for(const authMode of ['api_key','codex']){
    class ModelSettingsState {
      config = {auth_mode:authMode,base_url:'https://example.test',model:'synthetic',reasoning_effort:'auto',has_key:true,key_hint:'••••test'}
      saved = null
      codex = {logged_in:false,login:{status:'pending',method:'browser',auth_url:'https://example.test/device',device_code:{code:'synthetic-code'}}}
      models = []
      catalogNote = ''
      profiles = []
      activeId = null
      editingId = null
      name = ''
      effortChoices = ['auto']
      effortValid = true
      effortInvalid = false
      effortNote = ''
    }
    const settings = component('Settings',{
      './api':{api:browserApi},
      './modelSettingsState':{ModelSettingsState,effortLabel:(value:string)=>value},
    })
    const html = await renderToString(createSSRApp(settings))
    assert.match(html,/当前浏览器加密保存/)
    assert.match(html,/首次配置和设备码登录均在本浏览器完成/)
    assert.match(html,/无状态模型转发服务/)
    assert.match(html,/自定义API可由浏览器直连/)
    assert.match(html,/清除网站数据会删除本地问诊记录、模型配置和授权/)
    assert.doesNotMatch(html,/由Android设备加密保存|电脑浏览器登录|提交回调网址/)
    if(authMode==='api_key') assert.match(html,/已保存密钥标识/)
    else assert.match(html,/设备码登录/)
  }
})
