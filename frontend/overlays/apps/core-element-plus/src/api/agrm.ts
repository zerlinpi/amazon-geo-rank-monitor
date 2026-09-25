import axios from 'axios'

const client = axios.create({
  baseURL: import.meta.env.VITE_AGRM_API_BASEURL || 'http://localhost:8000',
  timeout: 120000,
  withCredentials: true,
})

function readCookie(name: string) {
  const prefix = `${encodeURIComponent(name)}=`
  const value = document.cookie
    .split('; ')
    .find(item => item.startsWith(prefix))
  return value ? decodeURIComponent(value.slice(prefix.length)) : ''
}

client.interceptors.request.use((config) => {
  const key = localStorage.getItem('token')
  if (key?.startsWith('agrm_')) {
    config.headers['X-API-Key'] = key
  }
  const method = (config.method || 'get').toLowerCase()
  if (!['get', 'head', 'options'].includes(method)) {
    const csrf = readCookie('agrm_csrf')
    if (csrf) {
      config.headers['X-CSRF-Token'] = csrf
    }
  }
  return config
})

client.interceptors.response.use(
  response => response.data,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token')
      localStorage.removeItem('authMode')
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

export interface WorkspaceMembership {
  id: string
  owner_id: string
  user_id: string
  role: 'owner' | 'admin' | 'analyst' | 'viewer'
  workspace_name?: string
  created_at: string
}

export interface AccountProfile {
  user: {
    id: string
    email: string
    display_name: string
  }
  workspace: {
    id: string
    name: string
    role: 'owner' | 'admin' | 'analyst' | 'viewer'
  }
  memberships: WorkspaceMembership[]
}

export interface SessionResult extends AccountProfile {
  expires_at: string
}

export interface UserSession {
  id: string
  owner_id: string
  created_at: string
  expires_at: string
  last_seen_at: string
  created_ip?: string | null
  last_seen_ip?: string | null
  user_agent?: string | null
  current: boolean
}

export interface TeamMember extends WorkspaceMembership {
  email: string
  display_name: string
  disabled_at?: string | null
}

export interface WorkspaceInvitation {
  id: string
  owner_id?: string
  email: string
  role: string
  invitation_token?: string
  created_at?: string
  expires_at: string
  accepted_at?: string | null
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
  last_used_ip?: string | null
  usage_count: number
  revoked_at?: string | null
  scopes: string[]
}

export interface AuditEvent {
  id: string
  owner_id: string
  api_key_id?: string | null
  user_id?: string | null
  actor_type?: 'api_key' | 'session' | string
  request_id: string
  method: string
  path: string
  status_code: number
  client_ip?: string | null
  user_agent?: string | null
  created_at: string
}

export interface WorkerStatus {
  worker_id: string
  worker_type: string
  status: string
  last_job_id?: string | null
  last_error?: string | null
  processed_jobs: number
  started_at: string
  last_seen_at: string
}

export interface QueueSummary {
  counts: Record<string, number>
  oldest_pending_at?: string | null
}

export interface RankJob {
  id: string
  owner_id: string
  monitor_target_id?: string | null
  provider_mode: string
  status: string
  available_at: string
  claimed_at?: string | null
  claimed_by?: string | null
  lease_expires_at?: string | null
  completed_at?: string | null
  run_id?: string | null
  error?: string | null
  attempt_count: number
  max_attempts: number
  created_at: string
}

export interface CheckoutResult {
  payment_id: string
  checkout_session_id: string
  checkout_url: string
}

export const agrmApi = {
  registerAccount: (payload: {
    email: string
    password: string
    display_name: string
    workspace_name?: string
    invitation_token?: string
  }) => data<SessionResult>(client.post('/api/v1/auth/register', payload)),
  loginAccount: (payload: {
    email: string
    password: string
    workspace_id?: string
  }) => data<SessionResult>(client.post('/api/v1/auth/login', payload)),
  getMe: () => data<AccountProfile>(client.get('/api/v1/auth/me')),
  logoutAccount: () => data<void>(client.post('/api/v1/auth/logout')),
  logoutAll: () => data<void>(client.post('/api/v1/auth/logout-all')),
  getSessions: () => data<UserSession[]>(client.get('/api/v1/auth/sessions')),
  revokeSession: (id: string) => data<void>(client.delete('/api/v1/auth/sessions/' + id)),
  changePassword: (current_password: string, new_password: string) => data<{
    revoked_other_sessions: number
  }>(client.post('/api/v1/auth/change-password', { current_password, new_password })),
  switchWorkspace: (workspace_id: string) => data<SessionResult>(
    client.post('/api/v1/auth/switch-workspace', { workspace_id }),
  ),
  acceptInvitation: (invitation_token: string) => data<SessionResult>(
    client.post('/api/v1/auth/accept-invitation', { invitation_token }),
  ),
  getTeamMembers: () => data<TeamMember[]>(client.get('/api/v1/team/members')),
  getTeamInvitations: () => data<WorkspaceInvitation[]>(
    client.get('/api/v1/team/invitations'),
  ),
  createTeamInvitation: (email: string, role: string) => data<WorkspaceInvitation>(
    client.post('/api/v1/team/invitations', { email, role }),
  ),
  updateTeamMemberRole: (userId: string, role: string) => data<WorkspaceMembership>(
    client.patch('/api/v1/team/members/' + userId, { role }),
  ),
  removeTeamMember: (userId: string) => data<void>(
    client.delete('/api/v1/team/members/' + userId),
  ),
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
  createApiKey: (name: string, scopes: string[] = ['*']) => data<{
    id: string
    prefix: string
    plaintext: string
    scopes: string[]
  }>(
    client.post('/api/v1/api-keys', { name, scopes }),
  ),
  revokeApiKey: (id: string) => data<void>(client.delete('/api/v1/api-keys/' + id)),
  getSystemWorkers: () => data<WorkerStatus[]>(client.get('/api/v1/system/workers')),
  getQueueSummary: () => data<QueueSummary>(client.get('/api/v1/system/queue')),
  getDeadLetters: (limit = 50) => data<RankJob[]>(
    client.get('/api/v1/system/dead-letters', { params: { limit } }),
  ),
  requeueDeadLetter: (id: string) => data<RankJob>(
    client.post('/api/v1/system/dead-letters/' + id + '/requeue'),
  ),
  getAuditEvents: (limit = 100, api_key_id?: string) => data<AuditEvent[]>(
    client.get('/api/v1/system/audit', { params: { limit, api_key_id } }),
  ),
}

export default client
