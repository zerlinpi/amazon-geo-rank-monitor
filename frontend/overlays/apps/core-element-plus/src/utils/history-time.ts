export function historyTimeFilters(range: Date[] | null): {
  started_from?: string
  started_until?: string
} {
  if (range === null) {
    return {}
  }
  const [start, end] = range
  if (
    range.length !== 2 || !(start instanceof Date) || !(end instanceof Date)
    || !Number.isFinite(start.getTime()) || !Number.isFinite(end.getTime())
    || start > end
  ) {
    throw new RangeError('Choose a valid start and end time, with the start no later than the end.')
  }
  return { started_from: start.toISOString(), started_until: end.toISOString() }
}

export function recentHistoryRange(hours: number, now = new Date()): [Date, Date] {
  return [new Date(now.getTime() - hours * 60 * 60 * 1000), new Date(now.getTime())]
}
