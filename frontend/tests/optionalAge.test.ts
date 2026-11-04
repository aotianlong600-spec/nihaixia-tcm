import assert from 'node:assert/strict'
import test from 'node:test'
import { visitPayload, blankVisit } from '../src/visitState.ts'
test('clearing optional age omits it instead of posting an empty string to the numeric API field',()=>{
 const draft=blankVisit('patient-a')
 ;(draft.context as any).age_years=''
 assert.equal('age_years' in visitPayload(draft).context,false)
})
