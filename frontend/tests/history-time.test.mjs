import assert from 'node:assert/strict'
import { test } from 'node:test'
import { historyTimeFilters, recentHistoryRange } from '../overlays/apps/core-element-plus/src/utils/history-time.ts'

test('clearing the range removes both time filters', () => {
  assert.deepEqual(historyTimeFilters(null), {})
})

test('local picker dates become unambiguous UTC query bounds', () => {
  assert.deepEqual(historyTimeFilters([
    new Date('2026-09-28T09:00:00+08:00'),
    new Date('2026-09-28T10:00:00+08:00'),
  ]), {
    started_from: '2026-09-28T01:00:00.000Z',
    started_until: '2026-09-28T02:00:00.000Z',
  })
})

test('range preserves both occurrences of a repeated DST clock hour', () => {
  assert.deepEqual(historyTimeFilters([
    new Date('2026-11-01T01:30:00-04:00'),
    new Date('2026-11-01T01:30:00-05:00'),
  ]), {
    started_from: '2026-11-01T05:30:00.000Z',
    started_until: '2026-11-01T06:30:00.000Z',
  })
})

test('inclusive bounds allow the same instant', () => {
  const instant = new Date('2026-09-28T01:00:00Z')
  assert.deepEqual(historyTimeFilters([instant, instant]), {
    started_from: '2026-09-28T01:00:00.000Z',
    started_until: '2026-09-28T01:00:00.000Z',
  })
})

test('invalid, incomplete, or reversed ranges are rejected before requesting history', () => {
  const start = new Date('2026-09-28T01:00:00Z')
  const end = new Date('2026-09-28T02:00:00Z')
  for (const range of [[end, start], [new Date('invalid'), end], [start], []]) {
    assert.throws(() => historyTimeFilters(range), RangeError)
  }
})

test('24-hour and 7-day shortcuts use one stable end instant', () => {
  const now = new Date('2026-09-28T12:34:56.789Z')
  assert.deepEqual(historyTimeFilters(recentHistoryRange(24, now)), {
    started_from: '2026-09-27T12:34:56.789Z',
    started_until: '2026-09-28T12:34:56.789Z',
  })
  assert.deepEqual(historyTimeFilters(recentHistoryRange(168, now)), {
    started_from: '2026-09-21T12:34:56.789Z',
    started_until: '2026-09-28T12:34:56.789Z',
  })
  assert.equal(now.toISOString(), '2026-09-28T12:34:56.789Z')
})
