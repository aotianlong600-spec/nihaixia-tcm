export async function sendConsultation(api:{post:(path:string,data:any)=>Promise<any>}, id:string, text:string) {
  await api.post(`/consultations/${encodeURIComponent(id)}/messages`,{text})
  return api.post('/model/jobs',{purpose:'consult',consultation_id:id,allow_send:true})
}
export function evidenceFor(ids:string[] = [], evidence:any[] = []) { return evidence.filter(item=>ids.includes(item.id)) }
export function isCurrent(requested:string, current:string) { return requested === current }
export function referencesFor(ids:string[] = [], frozen:any[] | null | undefined, current:any[] = []) { return evidenceFor(ids, frozen ?? current) }
export function referenceLink(e:any):any { return e.format === 'github' ? (e.source_url ? {kind:'external',url:e.source_url} : {kind:'none'}) : (e.source_id != null && e.unit_no != null ? {kind:'unit',source:e.source_id,unit:e.unit_no} : {kind:'none'}) }
export function locatorLabel(item:any):string {
  const l=item?.locator || {}; const start=l.start ?? item?.physical_page ?? item?.pdf_page; const end=l.end
  if (start == null) return '位置未提供'
  const range=end != null && end !== start ? `${start}–${end}` : `${start}`
  if ((l.kind === 'pdf_page' || l.kind === 'physical_page') || item?.physical_page != null || item?.pdf_page != null) return `PDF第${start}页`
  if (l.kind === 'line_range') return `原文第${range}行`
  if (l.kind === 'paragraph_range') return `第${range}段`
  if (l.kind === 'record') return `条目 ${start}`
  return `${l.kind || '位置'} ${range}`
}
export function roleLabel(role:string):string { return ({ni_core:'倪氏资料',reference:'参考医著',open_source_summary:'开源辨证归纳'} as Record<string,string>)[role] || role || '资料' }
export function shanghaiTime(time:string):string { const d=new Date(time);return Number.isNaN(d.getTime()) ? (time||'') : new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(d) }
export function actionLabel(action:string):string { return ({add:'增',remove:'减',replace:'替换',adjust:'调量',adjust_dose:'调量'} as Record<string,string>)[action] || action || '未提供' }
export function previewComponentLabel(c:any):string { const dose=c.source_dose == null || c.source_dose === '' ? '来源原量未提供' : `${c.source_dose}${c.source_unit || ''}`;return `${c.name || '药名未提供'}${c.processing ? `（${c.processing}）` : ''} · ${dose}` }
export function previewActionLabel(m:any):string { return `${actionLabel(m.action)} ${m.herb || '药名未提供'}${m.replacement ? ` → ${m.replacement}` : ''}${m.reason ? `：${m.reason}` : ''}` }
