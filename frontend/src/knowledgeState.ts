import { ApiClient } from './api.ts'
export interface KnowledgePage {
 document_id:string;physical_page:number;raw_text:string;corrected_text:string|null;
 review_status:string;kind:string;printed_page:string|number|null;warning:string
}
export class KnowledgeWorkspace {
 client:ApiClient
 targetDocumentId=''
 targetPhysicalPage=1
 page:KnowledgePage|null=null
 constructor(client:ApiClient){this.client=client}
 search(query:string){
  const params=new URLSearchParams({q:query,limit:'30'})
  if(this.targetDocumentId)params.set('document_id',this.targetDocumentId)
  return this.client.request(`/search?${params}`)
 }
 async load(id=this.targetDocumentId,n=this.targetPhysicalPage){
  this.page=await this.client.request<KnowledgePage>(`/documents/${encodeURIComponent(id)}/pages/${n}`)
  this.targetDocumentId=id;this.targetPhysicalPage=n
 }
 private loaded(){if(!this.page)throw Error('请先打开要校核的原文页');return this.page}
 get pdfUrl(){const page=this.loaded();return `/api/documents/${encodeURIComponent(page.document_id)}/pdf#page=${page.physical_page}`}
 async review(payload:unknown){
  const {document_id,physical_page}=this.loaded()
  const path=`/documents/${encodeURIComponent(document_id)}/pages/${physical_page}`
  await this.client.post(`${path}/review`,payload)
  this.page=await this.client.request<KnowledgePage>(path)
 }
 createEvidence(payload:object){
  const {document_id,physical_page}=this.loaded()
  return this.client.post('/evidence',{...payload,document_id,physical_page})
 }
}
