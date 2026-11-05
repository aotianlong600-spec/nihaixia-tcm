import type { ApiClient } from './api.ts'
export async function loadClinicalReferences(client:ApiClient){
 const rules=(await client.request('/rules')).items
 const evidence=(await client.request('/evidence')).items
 return {rules,evidence}
}

export function retainRuleSelection(rules:{id:string;kind:string;status:string;formula_id?:string;base_formula_id?:string}[], baseRule:string, modifications:string[]){
 const base=rules.find(r=>r.id===baseRule&&r.kind==='pattern'&&r.status==='published')
 return {baseRule:base?.id||'',modifications:base?modifications.filter(id=>rules.some(r=>r.id===id&&r.kind==='modification'&&r.status==='published'&&r.base_formula_id===base.formula_id)):[]}
}
