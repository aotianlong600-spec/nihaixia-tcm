const unique=(values:string[])=>Array.from(new Set(values))
const sameVersion=(a:any,b:any)=>a.package_id===b.package_id&&a.package_version===b.package_version

export function sourceRows(graph:any,identity:any,ids:string[]=[],evidence:any[]=[]){
 return unique(ids).map(id=>{
  const claim=(graph.claims||[]).find((c:any)=>sameVersion(c,identity)&&c.id===id)
  const anchors=(graph.anchors||[]).filter((a:any)=>sameVersion(a,identity)&&claim?.anchor_ids?.includes(a.id)).map((a:any)=>({...a,evidence:evidence.find(e=>e.id===`decision:${identity.package_id}@${identity.package_version}:${a.id}`)}))
  return {id,claim,anchors,missing:!claim||anchors.length!==unique(claim.anchor_ids||[]).length}
 })
}

export function conditionLabel(expr:any):string{
 if(!expr)return '条件未提供'
 if(expr.fact){
  if(expr.op)return `${expr.fact} ${({gt:'>',gte:'≥',lt:'<',lte:'≤',eq:'='} as Record<string,string>)[expr.op]||expr.op} ${expr.value} ${expr.unit||''}`
  return expr.state==='absent'?`明确否认 ${expr.fact}`:expr.fact
 }
 if(expr.not)return `不满足（${conditionLabel(expr.not)}）`
 if(expr.all||expr.any)return `${expr.all?'同时':'任一'}满足（${(expr.all||expr.any).map(conditionLabel).join('；')}）`
 return '条件未提供'
}

export function traceLabel(trace:any):string{
 if(trace?.conflicts?.length)return '冲突'
 return trace?.value===true?'满足':trace?.value===false?'不满足':'未知'
}

function componentClaims(component:any):string[]{return Object.values(component?.provenance||{}).flat() as string[]}
export function formulaClaimIds(formula:any):string[]{
 return unique([...(formula.identity_claim_ids||[]),...(formula.components||[]).flatMap(componentClaims),...(formula.preparation||[]).flatMap((p:any)=>p.claim_ids||[])])
}
export function modificationClaimIds(preview:any):string[]{
 return unique([...(preview.applied||[]),...(preview.unapplied||[])].flatMap((m:any)=>[...(m.claim_ids||[]),...(m.actions||[]).flatMap((a:any)=>[...(a.claim_ids||[]),...componentClaims(a.component)])]))
}
export function modificationLabel(preview:any):string{
 if(preview.conflicts?.length||preview.unapplied?.length)return '未应用，保留基方'
 if(preview.missing?.length)return '缺项，未应用'
 return preview.applied?.length?'差异预览已应用':'未应用'
}
