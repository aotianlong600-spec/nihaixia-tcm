import assert from 'node:assert/strict'
import test from 'node:test'
import { featureLabels } from '../src/literatureState.ts'

test('an explicitly absent finding is never displayed as positive symptom support',()=>{
  const entry={features:[{key:'汗出',expected:'absent'},{key:'恶风',expected:'present'}]}
  assert.deepEqual(featureLabels(entry,['汗出','恶风']),['汗出（原文明确无）','恶风'])
})
