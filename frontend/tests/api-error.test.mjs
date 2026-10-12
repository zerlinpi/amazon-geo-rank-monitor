import assert from 'node:assert/strict'
import { test } from 'node:test'
import { apiErrorMessage } from '../overlays/apps/core-element-plus/src/utils/api-error.ts'

test('validation responses identify fields instead of showing object strings', () => {
  assert.equal(apiErrorMessage({ response: { data: { detail: [
    { loc: ['body', 'keyword'], msg: 'Field required' },
    { loc: ['body', 'geo_profile_ids', 0], msg: 'Invalid value' },
  ] } } }, 'Save failed'), 'keyword: Field required; geo_profile_ids.0: Invalid value')
})

test('readable API errors are retained and network or malformed errors use a fallback', () => {
  assert.equal(apiErrorMessage({ response: { data: { detail: 'Insufficient credits' } } }, 'Run failed'), 'Insufficient credits')
  for (const error of [null, new Error('Network failure'), { response: { data: { detail: [null, {}] } } }]) {
    assert.equal(apiErrorMessage(error, 'Please try again'), 'Please try again')
  }
})
