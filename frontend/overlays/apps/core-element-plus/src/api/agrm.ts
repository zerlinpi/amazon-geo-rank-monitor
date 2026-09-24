import axios from 'axios'

const client = axios.create({
  baseURL: import.meta.env.VITE_AGRM_API_BASEURL || 'http://127.0.0.1:8000',
  timeout: 120000,
})

client.interceptors.request.use((config) => {
  const key = localStorage.getItem('token')
  if (key) {
    config.headers['X-API-Key'] = key
  }
  return config
})

client.interceptors.response.use(
  response => response.data,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token')
      if (location.hash !== '#/login') {
        location.hash = '#/login'
      }
    }
    return Promise.reject(error)
  },
)

function data<T>(promise: Promise<unknown>): Promise<T> {
  return promise as Promise<T>
}

export interface CreditBalance {
  balance: number
  reserved: number
  available: number
}

export interface CreditPack {
  id: string
  name: string
  credits: number
  amount_minor: number
  currency: string
}

export interface LedgerEntry {
  id: string
  entry_type: string
  delta_credits: number
  balance_after: number
  reference_type?: string | null
  reference_id?: string | null
  created_at: string
}

export interface GeoProfile {
  id: string
  name: string
  marketplace: string
  ip_country: string
  ip_state?: string | null
  ip_city?: string | null
  ip_postal_code?: string | null
  delivery_country: string
  delivery_postal_code: string
  device: 'desktop' | 'mobile'
  weight: string | number
  enabled: boolean
}

export interface Monitor {
  id: string
  name: string
  marketplace: string
  keyword: string
  asins: string[]
  geo_profile_ids: string[]
  search_depth: number
  provider_mode: 'managed' | 'strict'
  schedule?: string | null
  enabled: boolean
}

export interface RankSnapshot {
  asin: string
  weighted_rank: string
  found_weight: string
  missing_weight: string
  confidence: string
}

export interface RankObservation {
  asin: string
  geo_profile_id: string
  provider: string
  verification_level: string
  found: boolean
  organic_rank: number | null
  absolute_rank: number | null
  sponsored_rank: number | null
  effective_rank: number
  page: number | null
}

export interface RankRun {
  id: string
  marketplace: string
  keyword: string
  status: string
  requested_probe_count: number
  settled_probe_count: number
  error_summary?: string | null
  started_at: string
  completed_at?: string | null
  observations: RankObservation[]
  snapshots: RankSnapshot[]
}

export interface ApiKeyRow {
  id: string
  name: string
  prefix: string
  created_at?: string | null
  last_used_at?: string | null
  revoked_at?: string | null
}

export interface CheckoutResult {
  payment_id: string
  checkout_session_id: string
  checkout_url: string
}

export const agrmApi = {
  validateKey: () => data<CreditBalance>(client.get('/api/v1/credits')),
  getCredits: () => data<CreditBalance>(client.get('/api/v1/credits')),
  getLedger: (limit = 100) => data<LedgerEntry[]>(client.get('/api/v1/credits/ledger', { params: { limit } })),
  getCreditPacks: () => data<CreditPack[]>(client.get('/api/v1/billing/packs')),
  createCheckout: (credit_pack_id: string) => data<CheckoutResult>(
    client.post('/api/v1/billing/checkout', { credit_pack_id }),
  ),
  getGeoProfiles: () => data<GeoProfile[]>(client.get('/api/v1/geo-profiles')),
  createGeoProfile: (payload: Omit<GeoProfile, 'id'>) => data<GeoProfile>(
    client.post('/api/v1/geo-profiles', payload),
  ),
  getMonitors: () => data<Monitor[]>(client.get('/api/v1/monitors')),
  getMonitor: (id: string) => data<Monitor>(client.get('/api/v1/monitors/' + id)),
  createMonitor: (payload: Partial<Monitor>) => data<Monitor>(client.post('/api/v1/monitors', payload)),
  updateMonitor: (id: string, payload: Partial<Monitor>) => data<Monitor>(
    client.patch('/api/v1/monitors/' + id, payload),
  ),
  deleteMonitor: (id: string) => data<void>(client.delete('/api/v1/monitors/' + id)),
  runMonitor: (id: string) => data<any>(client.post('/api/v1/monitors/' + id + '/run')),
  checkRank: (payload: {
    marketplace: string
    keyword: string
    asins: string[]
    geo_profile_ids: string[]
    search_depth: number
    provider_mode: 'managed' | 'strict'
  }) => data<any>(client.post('/api/v1/rank/check', payload)),
  getRuns: (limit = 50) => data<RankRun[]>(client.get('/api/v1/runs', { params: { limit } })),
  getRun: (id: string) => data<RankRun>(client.get('/api/v1/runs/' + id)),
  getApiKeys: () => data<ApiKeyRow[]>(client.get('/api/v1/api-keys')),
  createApiKey: (name: string) => data<{ id: string, prefix: string, plaintext: string }>(
    client.post('/api/v1/api-keys', { name }),
  ),
  revokeApiKey: (id: string) => data<void>(client.delete('/api/v1/api-keys/' + id)),
}

export default client
