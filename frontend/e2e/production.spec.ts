import { expect, test } from '@playwright/test'

test.beforeEach(async ({ page, context }, info) => {
  await context.route('**/*', async (route) => {
    const host = new URL(route.request().url()).hostname
    if (!['127.0.0.1', 'localhost'].includes(host)) {
      throw new Error(`Unexpected external browser request: ${host}`)
    }
    await route.continue()
  })
  await page.goto('/#/login')
  await page.getByPlaceholder('you@company.com').fill(`${info.project.name}@example.com`)
  await page.locator('input[autocomplete="current-password"]').fill('offline-secure-password')
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page).toHaveURL(/\/#\/$/)
  await expect(page.getByRole('heading', { name: /Geo Rank|Dashboard|Rank overview/i }).first()).toBeVisible()
  const cookies = await context.cookies()
  expect(cookies.find(c => c.name === 'agrm_session')?.httpOnly).toBe(true)
  expect(await page.evaluate(() => localStorage.getItem('token'))).toBeNull()
})

async function history(page) {
  await page.goto('/#/ranking/history')
  await expect(page.getByRole('heading', { name: 'Run History' })).toBeVisible()
  await expect(page.getByText('Page 1 · 50 runs · newest first')).toBeVisible()
}

test('email configuration notices recover from errors and reflect configuration changes', async ({ page }) => {
  const endpoint = '**/api/v1/notifications/status'
  const warning = page.getByText('Email delivery is not configured', { exact: true })
  const refresh = page.getByRole('button', { name: 'Refresh delivery status', exact: true })
  await page.route(endpoint, route => route.fulfill({
    status: 503, json: { detail: 'Fixture unavailable' },
  }), { times: 1 })
  await page.goto('/#/workspace/alerts')
  await expect(page.getByText('Unable to load email configuration', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Create alert', exact: true })).toBeEnabled()
  await refresh.click()
  await expect(warning).toBeVisible()
  await page.route(endpoint, route => route.fulfill({
    json: { email: { configured: true } },
  }), { times: 1 })
  await refresh.click()
  await expect(warning).toBeHidden()

  await page.goto('/#/ranking/analytics')
  await expect(warning).toBeVisible()
  await page.goto('/#/workspace/system-status')
  await expect(warning).toBeVisible()
  await page.route(endpoint, route => route.fulfill({
    json: { email: { configured: true } },
  }), { times: 1 })
  await refresh.click()
  await expect(page.getByText('Email delivery configured', { exact: true })).toBeVisible()
  await expect(page.getByText('Configuration does not guarantee delivery.', { exact: false })).toBeVisible()
})

test('sending a report without SMTP records a visible failure and zero deliveries', async ({ page, context }, info) => {
  const csrf = (await context.cookies()).find(c => c.name === 'agrm_csrf')!.value
  const headers = { 'X-CSRF-Token': csrf }
  const geo = await context.request.post('http://127.0.0.1:8000/api/v1/geo-profiles', { headers, data: {
    id: `report-${info.project.name}`, name: 'Report New York', marketplace: 'amazon.com',
    ip_country: 'US', delivery_country: 'US', delivery_postal_code: '10001', weight: 100,
  } })
  expect(geo.status()).toBe(201)
  const monitor = await context.request.post('http://127.0.0.1:8000/api/v1/monitors', { headers, data: {
    name: 'Report monitor', marketplace: 'amazon.com', keyword: 'report delivery fixture',
    asins: ['B0TARGET01'], geo_profile_ids: [(await geo.json()).id],
    provider_mode: 'managed', search_depth: 100,
  } })
  expect(monitor.status()).toBe(201)
  const name = `Email configuration regression ${info.project.name}`
  const schedule = await context.request.post('http://127.0.0.1:8000/api/v1/reports/schedules', {
    headers, data: {
      name, monitor_target_ids: [(await monitor.json()).id],
      recipients: ['fixture@example.com'], schedule: '0 9 * * 1',
      lookback_hours: 168, include_csv: true, enabled: true,
    },
  })
  expect(schedule.status()).toBe(201)
  const id = (await schedule.json()).id
  await page.goto('/#/ranking/analytics')
  const response = page.waitForResponse(r => r.url().endsWith(`/api/v1/reports/schedules/${id}/send`))
  await page.getByRole('row').filter({ hasText: name }).getByRole('button', { name: 'Send now', exact: true }).click()
  expect((await response).status()).toBe(200)
  const delivery = await (await response).json()
  expect(delivery.status).toBe('failed')
  expect(delivery.sent_count).toBe(0)
  const history = page.locator('.el-card').filter({ has: page.getByText('Report delivery history', { exact: true }) })
  await expect(history.getByText('0/1', { exact: true })).toBeVisible()
  await expect(history.getByText('failed', { exact: true })).toBeVisible()
  await expect(history.getByText('Email delivery is not configured', { exact: true })).toBeVisible()
})

test('50-row pages and lazy detail loading', async ({ page }) => {
  const details: string[] = []
  page.on('request', r => {
    if (/\/api\/v1\/runs\/[a-f0-9-]+$/.test(r.url())) details.push(r.url())
  })
  await history(page)
  expect(details).toHaveLength(0)
  await expect(page.getByRole('button', { name: 'Newer', exact: true })).toBeDisabled()
  await page.getByRole('button', { name: 'Older', exact: true }).click()
  await expect(page.getByText('Page 2 · 50 runs · newest first')).toBeVisible()
  await page.getByRole('button', { name: 'Older', exact: true }).click()
  await expect(page.getByText('Page 3 · 5 runs · newest first')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Older', exact: true })).toBeDisabled()
  await page.getByRole('button', { name: 'Newer', exact: true }).click()
  await expect(page.getByText('Page 2 · 50 runs · newest first')).toBeVisible()
  await page.getByRole('button', { name: 'View', exact: true }).first().click()
  await expect(page.getByRole('dialog', { name: 'Rank run details' })).toBeVisible()
  await expect(page.getByRole('dialog').getByText('B0TARGET01', { exact: true }).first()).toBeVisible()
  expect(details).toHaveLength(1)
})

test('keyword ASIN status and empty state', async ({ page }) => {
  await history(page)
  await page.getByPlaceholder('e.g. trailer hitch').fill('TRAILER')
  await page.getByPlaceholder('Exact ASIN').fill('b0target01')
  // Element Plus renders the display label above its readonly inner input.
  await page.locator('.el-select').filter({
    has: page.getByRole('combobox', { name: 'Run status' }),
  }).click()
  await page.getByRole('option', { name: 'Failed', exact: true }).click()
  await page.getByRole('button', { name: 'Search / refresh' }).click()
  await expect(page.getByText('Page 1 · 1 runs · newest first')).toBeVisible()
  await page.getByPlaceholder('e.g. trailer hitch').fill('no matching keyword')
  await page.getByRole('button', { name: 'Search / refresh' }).click()
  await expect(page.getByText('No runs match these filters.')).toBeVisible()
})

test('shortcuts, manual local range, UTC request and clear', async ({ page }, info) => {
  await history(page)
  const zone = info.project.use.timezoneId as string
  await expect(page.getByText(`${zone} · Includes both endpoints. Clear for all dates.`)).toBeVisible()
  for (const [label, hours] of [['Last 24 hours', 24], ['Last 7 days', 168], ['Last 30 days', 720]] as const) {
    await page.getByPlaceholder('Start time').click()
    await page.getByRole('button', { name: label, exact: true }).click()
    const request = page.waitForRequest(r => r.url().includes('/api/v1/runs/page?'))
    await page.getByRole('button', { name: 'Search / refresh' }).click()
    const params = new URL((await request).url()).searchParams
    expect(params.get('started_from')).toMatch(/Z$/)
    expect(Date.parse(params.get('started_until')!) - Date.parse(params.get('started_from')!)).toBe(hours * 3600000)
    await expect(page.getByRole('button', { name: 'Search / refresh' })).toBeEnabled()
  }
  await page.getByPlaceholder('Start time').fill('2026-09-01 00:00:00')
  await page.getByPlaceholder('End time').fill('2026-09-02 00:00:00')
  await page.getByPlaceholder('End time').press('Tab')
  const request = page.waitForRequest(r => r.url().includes('/api/v1/runs/page?'))
  await page.getByRole('button', { name: 'Search / refresh' }).click()
  const params = new URL((await request).url()).searchParams
  const expected = await page.evaluate(() => new Date(2026, 8, 1, 0).toISOString())
  expect(params.get('started_from')).toBe(expected)
  await expect(page.getByRole('button', { name: 'Search / refresh' })).toBeEnabled()
  await page.locator('.el-date-editor').hover()
  await page.locator('.el-range__close-icon').click()
  const cleared = page.waitForRequest(r => r.url().includes('/api/v1/runs/page?'))
  await page.getByRole('button', { name: 'Search / refresh' }).click()
  expect(new URL((await cleared).url()).searchParams.has('started_from')).toBe(false)
  await expect(page.getByText('Page 1 · 50 runs · newest first')).toBeVisible()
})

test('loading, list failure/retry, detail failure/retry', async ({ page }) => {
  let release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  await page.route('**/api/v1/runs/page?*', async route => {
    await gate
    await route.fulfill({ status: 503, json: { detail: 'Fixture unavailable' } })
  }, { times: 1 })
  await page.goto('/#/ranking/history')
  await expect(page.locator('.el-loading-mask').first()).toBeVisible()
  release()
  await expect(page.getByText('Unable to load run history. Please try again.')).toBeVisible()
  await page.getByRole('button', { name: 'Search / refresh' }).click()
  await expect(page.getByText('Page 1 · 50 runs · newest first')).toBeVisible()
  await page.route(/\/api\/v1\/runs\/[a-f0-9-]+$/, route => route.fulfill({ status: 503, json: { detail: 'Fixture unavailable' } }), { times: 1 })
  await page.getByRole('button', { name: 'View', exact: true }).first().click()
  await expect(page.getByText('Unable to load this run. Please try again.')).toBeVisible()
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(page.getByRole('dialog').getByText('B0TARGET01', { exact: true }).first()).toBeVisible()
})

test('real account session creates monitor and worker result reaches history and analytics', async ({ page, context }, info) => {
  const csrf = (await context.cookies()).find(c => c.name === 'agrm_csrf')!.value
  const headers = { 'X-CSRF-Token': csrf }
  const geo = await context.request.post('http://127.0.0.1:8000/api/v1/geo-profiles', { headers, data: {
    id: `ny-${info.project.name}`, name: 'New York', marketplace: 'amazon.com',
    ip_country: 'US', delivery_country: 'US', delivery_postal_code: '10001', weight: 100,
  } })
  expect(geo.status()).toBe(201)
  const monitor = await context.request.post('http://127.0.0.1:8000/api/v1/monitors', { headers, data: {
    name: 'Browser monitor', marketplace: 'amazon.com', keyword: 'offline business',
    asins: ['B0TARGET01', 'B0TARGET02'], geo_profile_ids: [(await geo.json()).id], provider_mode: 'managed', search_depth: 100,
  } })
  expect(monitor.status()).toBe(201)
  const id = (await monitor.json()).id
  const queued = await context.request.post(`http://127.0.0.1:8000/api/v1/monitors/${id}/run`, { headers })
  expect(queued.status()).toBe(202)
  await expect.poll(async () => {
    const r = await context.request.get(`http://127.0.0.1:8000/api/v1/monitors/${id}/history`)
    return (await r.json())[0]?.job.status
  }).toBe('succeeded')
  await page.goto('/#/ranking/history')
  await page.getByPlaceholder('e.g. trailer hitch').fill('offline business')
  await page.getByRole('button', { name: 'Search / refresh' }).click()
  await expect(page.getByText('Page 1 · 1 runs · newest first')).toBeVisible()
  await page.getByRole('button', { name: 'View', exact: true }).click()
  await expect(page.getByRole('dialog').getByText('B0TARGET02', { exact: true }).first()).toBeVisible()
  const summary = await context.request.get(`http://127.0.0.1:8000/api/v1/analytics/monitors/${id}/summary`)
  expect((await summary.json()).run_count).toBe(1)
})
