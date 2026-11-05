export interface Fact {
  key:string; state:'present'|'absent'|'unknown'|'conflict'; verified:boolean;
  raw?:string; source?:'patient'|'clinician'|'test'; scope?:'current'|'history'; observed_at?:string;
  value?:string|number|null; unit?:string
  subject?:'patient'|'family'|'other'|'unknown'
}
export interface VisitDraft {
  id?:string; revision?:number; patient_id:string; previous_visit_id?:string; chief_complaint:string;
  facts:Fact[]; context:{simulation:boolean; age_years?:number; pregnancy:'yes'|'no'|'unknown'; allergies:string[]; medications:string[]}; clinician:string
}
export function canDecide(analysis: {visit_id:string;visit_revision:number;stale?:boolean}|null, visit:{id?:string;revision?:number}|null, dirty:boolean): boolean {
  return !!analysis && !!visit?.id && !dirty && !analysis.stale && analysis.visit_id === visit.id && analysis.visit_revision === visit.revision
}
export const blankVisit = (patient_id:string, previous_visit_id?:string): VisitDraft => ({patient_id, previous_visit_id, chief_complaint:'',facts:[],context:{simulation:true,pregnancy:'unknown',allergies:[],medications:[]},clinician:''})
export function visitPayload(draft:VisitDraft) {
  const {chief_complaint,facts,context,clinician}=draft
  const normalizedContext={...context}
  if (typeof normalizedContext.age_years !== 'number') delete normalizedContext.age_years
  const fields={chief_complaint,facts,context:normalizedContext,clinician}
  return draft.id ? {...fields,expected_revision:draft.revision} : {...fields,patient_id:draft.patient_id,previous_visit_id:draft.previous_visit_id}
}
