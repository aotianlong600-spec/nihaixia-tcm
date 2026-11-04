import assert from 'node:assert/strict'
import test from 'node:test'
import { visitPayload, blankVisit } from '../src/visitState.ts'
test('editing sends only editable API fields and revision, never visit identity or response metadata',()=>{
 const draft={...blankVisit('patient-a'),id:'visit-a',revision:3,chief_complaint:'合成',clinician:'验证医师',created_at:'2026-01-01'}
 assert.deepEqual(visitPayload(draft),{expected_revision:3,chief_complaint:'合成',facts:[],context:{simulation:true,pregnancy:'unknown',allergies:[],medications:[]},clinician:'验证医师'})
 assert.deepEqual(visitPayload({...blankVisit('patient-a','old-a'),clinician:'验证医师'}),{patient_id:'patient-a',previous_visit_id:'old-a',chief_complaint:'',facts:[],context:{simulation:true,pregnancy:'unknown',allergies:[],medications:[]},clinician:'验证医师'})
})
