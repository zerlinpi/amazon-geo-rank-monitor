export function apiErrorMessage(error: unknown, fallback: string): string {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const messages = detail.flatMap((item) => {
      if (typeof item?.msg !== 'string') return []
      const field = Array.isArray(item.loc) ? item.loc.filter((part: unknown) => part !== 'body').join('.') : ''
      return [field ? `${field}: ${item.msg}` : item.msg]
    })
    if (messages.length) return messages.join('; ')
  }
  return fallback
}
