import type { ApiClient } from './api.ts'
export async function loadClinicalReferences(client:ApiClient){
 const rules=(await client.request('/rules')).items
 const evidence=(await client.request('/evidence')).items
 return {rules,evidence}
}
