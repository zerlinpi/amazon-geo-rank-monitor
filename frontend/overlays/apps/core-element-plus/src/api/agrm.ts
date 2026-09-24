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
      if (!location.pathname.endsWith('/login')) {
        location.href = location.origin + location.pathname.replace(/\/$/, '') + '/login'
      }
    }
    return Promise.reject(error)
  },
)

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

export const agrmApi = {
  validateKey: () => client.get('/api/v1/credits'),
  getCredits: () => client.get('/api/v1/credits'),
  getLedger: (limit = 100) => client.get('/api/v1/credits/ledger', { params: { limit } }),
  getCreditPacks: () => client.get('/api/v1/billing/packs'),
  createCheckout: (credit_pack_id: string) => client.post('/api/v1/billing/checkout', { credit_pack_id }),
  getGeoProfiles: () => client.get('/api/v1/geo-profiles') as Promise<GeoProfile[]>,
  createGeoProfile: (payload: Omit<GeoProfile, 'id'>) => client.post('/api/v1/geo-profiles', payload),
  getMonitors: () => client.get('/api/v1/monitors') as Promise<Monitor[]>,
  getMonitor: (id: string) => client.get('/api/v1/monitors/' + id),
  createMonitor: (payload: Partial<Monitor>) => client.post('/api/v1/monitors', payload),
  runMonitor: (id: string) => client.post('/api/v1/monitors/' + id + '/run'),
  checkRank: (payload: {
    marketplace: string
    keyword: string
    asins: string[]
    geo_profile_ids: string[]
    search_depth: number
    provider_mode: 'managed' | 'strict'
  }) => client.post('/api/v1/rank/check', payload),
  getRuns: (limit = 50) => client.get('/api/v1/runs', { params: { limit } }) as Promise<RankRun[]>,
  getRun: (id: string) => client.get('/api/v1/runs/' + id) as Promise<RankRun>,
  getApiKeys: () => client.get('/api/v1/api-keys'),
  createApiKey: (name: string) => client.post('/api/v1/api-keys', { name }),
  revokeApiKey: (id: string) => client.delete('/api/v1/api-keys/' + id),
}

export default client
