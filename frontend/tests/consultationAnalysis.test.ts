import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {createRequire} from 'node:module'
import {parse, compileScript} from '@vue/compiler-sfc'
import {createSSRApp} from 'vue'
import {renderToString} from '@vue/server-renderer'
import ts from 'typescript'
import * as personalState from '../src/personalState.ts'

const require = createRequire(import.meta.url)
const localDecision = {default:{props:['graph','evidence','revision'],template:'<div data-local-decision="true"></div>'}}

function component(name:string, imports:Record<string,unknown>) {
  const source = readFileSync(new URL(`../src/${name}.vue`,import.meta.url),'utf8')
  const {descriptor} = parse(source)
  const compiled = compileScript(descriptor,{id:name,inlineTemplate:true})
  const output = ts.transpileModule(compiled.content,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText
  const module = {exports:{} as any}
  new Function('require','module','exports',output)((name:string)=>name in imports?imports[name]:require(name),module,module.exports)
  return module.exports.default
}

const analysis = {
  present:['口干','手足冷'],
  present_labels:{'口干':'口干','手足冷':'手足冷'},
  absent:['下利'],
  absent_labels:{'下利':'下利'},
  conflicts:['发热'],
  unknown:['汗出'],
  unverified_terms:['说不清'],
  items:[{
    formula_id:'formula-a',
    formula_name:'合成方甲',
    score:7.5,
    matched_terms:['口干'],
    matched_labels:{'口干':'口干'},
    matched_raw_terms:['有点烦'],
    missing_terms:['脉微细'],
    contradicted_terms:['下利'],
    evidence:[{source_id:'source-a',unit_no:12,source_title:'合成原文甲',locator:{kind:'line_range',start:3,end:4},quote:'口干，手足冷，合成引文。',quote_sha256:'a'.repeat(64)}],
    composition_versions:[
      {id:'v1',source:'合成来源一',components:[{name:'药甲',processing:'炙',source_dose:'三两',source_unit:''},{name:'药乙'}],raw_block:'药甲三两，药乙'},
      {id:'v2',source:'合成来源二',components:[{name:'药丙',source_dose:'二两',source_unit:''}],raw_block:'药丙二两'},
    ],
    modifications:[{
      condition:'若口渴',
      raw:'口渴者加药丁',
      actions:[{action:'add',herb:'药丁',dose:'一两',unit:''},{action:'remove',herb:'药乙'}],
      source:{source_id:'source-a',unit_no:12,locator:{kind:'line_range',start:5},source_title:'合成原文甲'},
      application_status:'applied',
      reason:'原文示例',
    }],
  }],
}

async function render(extra:Record<string,unknown>={}) {
  const app = component('ConsultationAnalysis',{
    './personalState':personalState,
    './LocalDecision.vue':localDecision,
  })
  return renderToString(createSSRApp(app,{analysis,...extra}))
}

function group(html:string,name:string) {
  const start = html.indexOf(`data-fact-group="${name}"`)
  assert.notEqual(start,-1,`missing fact group ${name}`)
  const end = html.indexOf('</div>',start)
  assert.notEqual(end,-1,`unclosed fact group ${name}`)
  return html.slice(start,end)
}

test('analysis keeps confirmed facts separate from conflicts, unknown and unverified lexical clues',async()=>{
  const html = await render()
  const confirmed = group(html,'confirmed')
  assert.match(confirmed,/已确认存在<\/strong>：口干、手足冷/)
  assert.match(confirmed,/已确认否认<\/strong>：下利/)
  assert.doesNotMatch(confirmed,/说不清/)
  assert.match(group(html,'conflicts'),/发热/)
  assert.match(group(html,'unknown'),/汗出/)
  const unverified = group(html,'unverified')
  assert.match(unverified,/说不清/)
  assert.match(unverified,/未确立为患者事实/)
})

test('candidates expose retrieval rank, clues, evidence and formula action without probability language',async()=>{
  const html = await render({graph:{nodes:[{id:'synthetic-node'}]}})
  assert.match(html,/检索排序分 7\.5 · 仅用于库内检索排序/)
  assert.match(html,/支持线索<\/strong>：口干/)
  assert.match(html,/词面命中（未核验）<\/strong>：有点烦/)
  assert.match(html,/原文提及、待核对<\/strong>：脉微细/)
  assert.match(html,/反证<\/strong>：下利/)
  assert.match(html,/合成原文甲 · 原文第3–4行/)
  assert.match(html,/合成引文/)
  assert.match(html,/查看方剂/)
  assert.match(html,/data-local-decision="true"/)
  assert.doesNotMatch(html,/概率|置信度|疗效/)
})

test('composition versions stay separate and missing doses show as not provided',async()=>{
  const html = await render()
  assert.match(html,/来源组成版本（2 个，独立展示）/)
  const versions = [...html.matchAll(/data-composition-version="([^"]+)"([\s\S]*?)<\/article>/g)]
  assert.equal(versions.length,2)
  const [first,second] = versions
  assert.match(first[2],/药甲（炙） · 来源原量 三两/)
  assert.match(first[2],/药乙 · 来源原量 未提供/)
  assert.doesNotMatch(first[2],/药丙/)
  assert.match(second[2],/药丙 · 来源原量 二两/)
  assert.doesNotMatch(second[2],/药甲|药乙/)
})

test('modification actions are listed as source clues and never marked applied',async()=>{
  const html = await render()
  assert.match(html,/原文加减线索/)
  assert.match(html,/本组件不据此调整组成/)
  assert.match(html,/口渴者加药丁/)
  assert.match(html,/增 药丁 · 一两/)
  assert.match(html,/减 药乙 · 剂量未提供/)
  assert.match(html,/合成原文甲 · 原文第5行/)
  assert.doesNotMatch(html,/已应用/)
  assert.doesNotMatch(html,/applied/)
})
