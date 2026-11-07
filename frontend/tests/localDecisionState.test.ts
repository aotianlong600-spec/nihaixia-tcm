import test from 'node:test'
import assert from 'node:assert/strict'
import {conditionLabel,traceLabel,sourceRows,formulaClaimIds,modificationClaimIds,modificationLabel} from '../src/localDecisionState.ts'

test('local source references resolve only the complete package and version identity',()=>{
 const graph={claims:[{id:'c',package_id:'p',package_version:1,text:'version one',anchor_ids:['a']},{id:'c',package_id:'p',package_version:2,text:'version two',anchor_ids:['a']},{id:'c',package_id:'other',package_version:1,text:'other package',anchor_ids:['a']}],anchors:[{id:'a',package_id:'p',package_version:1,source_id:'one',unit_no:7},{id:'a',package_id:'p',package_version:2,source_id:'two',unit_no:9}]}
 const before=JSON.stringify(graph)
 const evidence=[{id:'decision:p@1:a',title:'Synthetic first source'},{id:'decision:p@2:a',title:'Synthetic second source'}]
 const rows=sourceRows(graph,{package_id:'p',package_version:1},['c','c'],evidence)
 assert.equal(rows.length,1)
 assert.equal(rows[0].claim.text,'version one')
 assert.equal(rows[0].anchors[0].source_id,'one')
 assert.equal(rows[0].anchors[0].evidence.title,'Synthetic first source')
 assert.equal(rows[0].missing,false)
 assert.equal(sourceRows(graph,{package_id:'p',package_version:3},['c'],evidence)[0].missing,true)
 assert.equal(JSON.stringify(graph),before)
})

test('condition display retains OR, AND, explicit absence, comparisons and unknown/conflict',()=>{
 const terms=[{fact:'synthetic A'},{fact:'synthetic B',state:'absent'}]
 assert.match(conditionLabel({any:terms}),/任一/)
 assert.match(conditionLabel({all:terms}),/同时/)
 assert.match(conditionLabel({any:terms}),/明确否认.*synthetic B/)
 assert.match(conditionLabel({fact:'synthetic temperature',op:'gte',value:38,unit:'°C'}),/≥ 38 °C/)
 assert.equal(traceLabel({value:null,missing:['a'],conflicts:[]}), '未知')
 assert.equal(traceLabel({value:true,conflicts:['a']}),'冲突')
 assert.equal(traceLabel({value:false,conflicts:[]}),'不满足')
})

test('formula and modification field references stay explicit, while failed differences remain unapplied',()=>{
 const component={name:'synthetic herb',provenance:{name:['identity'],processing:['processing'],source_dose:[],source_unit:[]}}
 assert.deepEqual(formulaClaimIds({identity_claim_ids:['identity'],components:[component],preparation:[{claim_ids:['preparation']}]}),['identity','processing','preparation'])
 const preview={applied:[],unapplied:[{claim_ids:['trigger'],actions:[{claim_ids:['action'],component}]}],diff:[{operation:'add',after:component}],conflicts:['synthetic conflict'],missing:[]}
 assert.deepEqual(modificationClaimIds(preview),['trigger','action','identity','processing'])
 assert.equal(modificationLabel(preview),'未应用，保留基方')
 assert.equal(modificationLabel({applied:[{}],unapplied:[],conflicts:[],missing:[]}),'差异预览已应用')
 assert.equal(modificationLabel({applied:[],unapplied:[],conflicts:[],missing:['x']}),'缺项，未应用')
})
