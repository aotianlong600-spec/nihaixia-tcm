import assert from 'node:assert/strict'
import test from 'node:test'
import { isValidatedModelResult } from '../src/modelState.ts'
test('partial, cancelled and unvalidated output is preview only, even when text looks complete',()=>{
  assert.equal(isValidatedModelResult({status:'running',validated:true}),false)
  assert.equal(isValidatedModelResult({status:'cancelled',validated:true}),false)
  assert.equal(isValidatedModelResult({status:'completed',validated:false}),false)
  assert.equal(isValidatedModelResult({status:'completed'}),false)
  assert.equal(isValidatedModelResult({status:'completed',validated:true}),true)
})
