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
    const csrf = readCookie(import.meta.env.VITE_AGRM_CSRF_COOKIE_NAME || 'agrm_csrf')
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
  require_mfa?: boolean
  created_at: string
}

export interface AccountProfile {
  user: {
    id: string
    email: string
    display_name: string
    email_verified: boolean
    email_verified_at?: string | null
    mfa_enabled: boolean
    mfa_authenticated: boolean
    recovery_codes_remaining: number
  }
  workspace: {
    id: string
    name: string
    role: 'owner' | 'admin' | 'analyst' | 'viewer'
    require_mfa: boolean
    mfa_setup_required: boolean
    mfa_session_verification_required: boolean
    enforce_sso: boolean
    sso_authenticated: boolean
  }
  memberships: WorkspaceMembership[]
}

export interface SessionResult extends AccountProfile {
  expires_at: string
  mfa_required?: false
}

export interface MfaChallengeResult {
  mfa_required: true
  challenge_token: string
  expires_at: string
}

export type LoginResult = SessionResult | MfaChallengeResult

export interface MfaEnrollmentResult {
  secret: string
  provisioning_uri: string
}

export interface WorkspaceSecurityPolicy {
  owner_id: string
  require_mfa: boolean
}

export interface WorkspaceVerificationPolicy {
  owner_id: string
  enabled?: boolean | null
  min_confidence?: string | number | null
  max_upstream_probes_per_run?: number | null
  runtime: {
    enabled: boolean
    min_confidence: string | number
    max_upstream_probes_per_run: number
  }
  effective: {
    enabled: boolean
    min_confidence: string | number
    max_upstream_probes_per_run: number
  }
}

export interface WorkspaceVerificationPolicyUpdate {
  enabled?: boolean | null
  min_confidence?: number | null
  max_upstream_probes_per_run?: number | null
}

export interface SsoDiscovery {
  workspace_id: string
  display_name: string
  provider_type: 'google' | 'entra' | 'oidc' | string
}

export interface WorkspaceSsoConfig {
  owner_id: string
  provider_type: 'google' | 'entra' | 'oidc' | string
  display_name: string
  issuer_url: string
  client_id: string
  email_domains: string[]
  auto_join: boolean
  enabled: boolean
  enforce_sso: boolean
  verified_at?: string | null
  created_at?: string | null
  updated_at?: string | null
}

export interface WorkspaceSsoConfigUpdate {
  provider_type: 'google' | 'entra' | 'oidc' | string
  display_name: string
  issuer_url: string
  client_id: string
  client_secret?: string
  email_domains: string[]
  auto_join: boolean
  enabled: boolean
}

export interface SsoStartResult {
  authorization_url: string
  expires_at: string
}

export interface WorkspaceScimConfig {
  owner_id: string
  enabled: boolean
  default_role: 'admin' | 'analyst' | 'viewer'
  token_prefix?: string | null
  has_token: boolean
  created_at?: string | null
  updated_at?: string | null
}

export interface ScimTokenResult {
  token: string
  prefix: string
}

export interface ScimAdminGroup {
  id: string
  owner_id: string
  external_id?: string | null
  display_name: string
  mapped_role?: 'admin' | 'analyst' | 'viewer' | null
  created_at: string
  updated_at: string
  members: {
    membership_id: string
    user_id: string
    email: string
    display_name: string
  }[]
}

export interface AuthSecurityEvent {
  id: string
  user_id?: string | null
  email: string
  event_type: string
  success: boolean
  client_ip?: string | null
  user_agent?: string | null
  details?: Record<string, any> | null
  created_at: string
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
  mfa_authenticated_at?: string | null
}

export interface TeamMember extends WorkspaceMembership {
  email: string
  display_name: string
  disabled_at?: string | null
  mfa_enabled?: boolean
  suspended_at?: string | null
  scim_managed?: boolean
  scim_external_id?: string | null
  updated_at?: string | null
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
  auto_strict_enabled?: boolean | null
  auto_strict_min_confidence?: string | number | null
  auto_strict_max_probes_per_run?: number | null
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
  probe_source: 'upstream' | 'cache'
  cache_age_seconds?: number | null
}

export interface RankUsage {
  requested_probe_count: number
  upstream_probe_count: number
  cache_hit_count: number
  billable_probe_count: number
}

export interface RankCheckResult {
  run_id: string
  status: string
  errors: string[]
  usage: RankUsage
  verification: {
    manual_force_requested?: boolean
    auto_strict_events: VerificationEvent[]
    strict_attempted: boolean
    strict_succeeded: boolean
  }
  observations: RankObservation[]
  snapshots: RankSnapshot[]
}

export interface AnalyticsAggregatePoint {
  run_id: string
  completed_at: string
  run_status: string
  asin: string
  weighted_rank: string | number
  found_weight: string | number
  missing_weight: string | number
  confidence: string | number
}

export interface AnalyticsGeoPoint {
  run_id: string
  completed_at: string
  run_status: string
  asin: string
  geo_profile_id: string
  found: boolean
  organic_rank?: number | null
  absolute_rank?: number | null
  sponsored_rank?: number | null
  effective_rank: number
  provider: string
  verification_level: string
}

export interface AnalyticsTrend {
  monitor: {
    id: string
    name: string
    marketplace: string
    keyword: string
    asins: string[]
    geo_profile_ids: string[]
  }
  window: {
    start: string
    end: string
    hours: number
  }
  aggregate: AnalyticsAggregatePoint[]
  geo: AnalyticsGeoPoint[]
}

export interface AnalyticsAsinSummary {
  asin: string
  run_count: number
  first_rank: string | number
  latest_rank: string | number
  change: string | number
  best_rank: string | number
  worst_rank: string | number
  average_rank: string | number
  average_confidence: string | number
  average_found_rate: string | number
}

export interface AnalyticsGeoSummary {
  asin: string
  geo_profile_id: string
  observation_count: number
  found_count: number
  found_rate: string | number
  best_effective_rank: string | number
  worst_effective_rank: string | number
  average_effective_rank: string | number
}

export interface AnalyticsSummary {
  monitor: AnalyticsTrend['monitor']
  window: AnalyticsTrend['window']
  run_count: number
  asins: AnalyticsAsinSummary[]
  geos: AnalyticsGeoSummary[]
}

export interface CompetitiveRow {
  asin: string
  title?: string | null
  tracked: boolean
  organic_appearances: number
  sponsored_appearances: number
  organic_sov_pct: number
  sponsored_sov_pct: number
  organic_probe_coverage_pct: number
  sponsored_probe_coverage_pct: number
  best_organic_rank?: number | null
  average_organic_rank?: number | null
  best_sponsored_rank?: number | null
  average_sponsored_rank?: number | null
  latest_organic_rank?: number | null
  organic_rank_change?: number | null
  run_count: number
  geo_count: number
}

export interface CompetitiveSummary {
  monitor: {
    id: string
    name: string
    marketplace: string
    keyword: string
    tracked_asins: string[]
  }
  window: {
    start: string
    end: string
    hours: number
    top_n: number
  }
  probe_count: number
  organic_slot_count: number
  sponsored_slot_count: number
  competitors: CompetitiveRow[]
  geo_leaders: {
    geo_profile_id: string
    leaders: {
      asin: string
      appearances: number
      average_organic_rank: number
      best_organic_rank: number
    }[]
  }[]
}

export interface CompetitiveTrendPoint {
  run_id: string
  completed_at: string
  asin: string
  average_organic_rank?: number | null
  best_organic_rank?: number | null
  organic_probe_coverage_pct: number
  sponsored_appearances: number
}

export interface CompetitiveTrend {
  monitor: {
    id: string
    name: string
    marketplace: string
    keyword: string
  }
  window: {
    start: string
    end: string
    hours: number
    top_n: number
  }
  asins: string[]
  series: CompetitiveTrendPoint[]
}

export interface ReportSchedule {
  id: string
  owner_id: string
  name: string
  monitor_target_ids: string[]
  recipients: string[]
  schedule: string
  lookback_hours: number
  include_csv: boolean
  enabled: boolean
  created_at: string
  updated_at: string
}

export interface ReportSchedulePayload {
  name: string
  monitor_target_ids: string[]
  recipients: string[]
  schedule: string
  lookback_hours: number
  include_csv: boolean
  enabled: boolean
}

export interface ReportDelivery {
  id: string
  owner_id: string
  schedule_id: string
  scheduled_for: string
  status: 'sent' | 'partially_failed' | 'failed' | 'sending' | string
  recipient_count: number
  sent_count: number
  subject: string
  summary: Record<string, any>
  error?: string | null
  created_at: string
  completed_at?: string | null
}

export interface AlertRule {
  id: string
  owner_id: string
  monitor_target_id: string
  name: string
  rule_type: 'rank_drop' | 'rank_improve' | 'enters_top_n' | 'exits_top_n' | 'not_found' | 'geo_not_found' | 'geo_rank_above' | 'competitor_enters_top_n' | 'competitor_exits_top_n' | 'competitor_sov_gain' | 'competitor_sov_loss' | 'competitor_overtakes_tracked' | string
  threshold?: string | number | null
  asin?: string | null
  geo_profile_id?: string | null
  channels: {
    email_count: number
    emails: string[]
    has_slack: boolean
    has_webhook: boolean
  }
  cooldown_minutes: number
  enabled: boolean
  created_at: string
  updated_at: string
}

export interface AlertChannelsInput {
  emails: string[]
  slack_webhook_url?: string | null
  webhook_url?: string | null
}

export interface AlertRulePayload {
  monitor_target_id: string
  name: string
  rule_type: string
  threshold?: number | null
  asin?: string | null
  geo_profile_id?: string | null
  channels: AlertChannelsInput
  cooldown_minutes: number
  enabled: boolean
}

export interface AlertDelivery {
  id: string
  event_id: string
  channel_type: string
  destination: string
  status: string
  error?: string | null
  attempted_at: string
}

export interface AlertEvent {
  id: string
  owner_id: string
  rule_id: string
  monitor_target_id: string
  run_id: string
  asin: string
  geo_profile_id?: string | null
  event_type: string
  previous_value?: string | number | null
  current_value?: string | number | null
  details: Record<string, any>
  created_at: string
  deliveries: AlertDelivery[]
}

export interface VerificationEvent {
  geo_profile_id: string
  requested: boolean
  attempted: boolean
  succeeded: boolean
  cache_hit: boolean
  triggers: string[]
  skipped_reason?: string | null
  error?: string | null
}

export interface VerificationMetadata {
  manual_force_requested?: boolean
  manual_force_effective?: boolean
  auto_strict_enabled?: boolean
  auto_strict_min_confidence?: string | number | null
  auto_strict_max_upstream_probes_per_run?: number | null
  strict_upstream_attempt_count?: number
  strict_requested_count?: number
  strict_attempted_count?: number
  strict_succeeded_count?: number
  strict_skipped_count?: number
  events?: VerificationEvent[]
}

export interface VerificationSummary {
  strict_requested: number
  strict_attempted: number
  strict_succeeded: number
  strict_skipped: number
}

export interface RankRun {
  id: string
  marketplace: string
  keyword: string
  status: string
  requested_probe_count: number
  settled_probe_count: number
  cache_hit_count: number
  verification_metadata?: VerificationMetadata
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
  }) => data<LoginResult>(client.post('/api/v1/auth/login', payload)),
  completeMfa: (challenge_token: string, code: string, remember_device: boolean) => data<SessionResult>(
    client.post('/api/v1/auth/mfa/complete', {
      challenge_token,
      code,
      remember_device,
    }),
  ),
  beginMfaEnrollment: () => data<MfaEnrollmentResult>(
    client.post('/api/v1/auth/mfa/enroll'),
  ),
  confirmMfaEnrollment: (code: string) => data<{ enabled: boolean, recovery_codes: string[] }>(
    client.post('/api/v1/auth/mfa/enroll/verify', { code }),
  ),
  verifyCurrentSessionMfa: (code: string) => data<{ verified: boolean }>(
    client.post('/api/v1/auth/mfa/session-verify', { code }),
  ),
  regenerateRecoveryCodes: (code: string) => data<{ recovery_codes: string[] }>(
    client.post('/api/v1/auth/mfa/recovery-codes/regenerate', { code }),
  ),
  disableMfa: (current_password: string, code: string) => data<{ enabled: boolean }>(
    client.post('/api/v1/auth/mfa/disable', { current_password, code }),
  ),
  getMe: () => data<AccountProfile>(client.get('/api/v1/auth/me')),
  discoverSso: (email: string) => data<SsoDiscovery[]>(
    client.get('/api/v1/auth/sso/discover', { params: { email } }),
  ),
  startSso: (workspace_id: string, email?: string) => data<SsoStartResult>(
    client.post('/api/v1/auth/sso/start', { workspace_id, email }),
  ),
  forgotPassword: (email: string) => data<{ accepted: boolean, message: string }>(
    client.post('/api/v1/auth/forgot-password', { email }),
  ),
  resetPassword: (token: string, new_password: string) => data<{
    reset: boolean
    revoked_sessions: number
  }>(client.post('/api/v1/auth/reset-password', { token, new_password })),
  verifyEmail: (token: string) => data<{
    verified: boolean
    email: string
    email_verified_at: string
  }>(client.post('/api/v1/auth/verify-email', { token })),
  resendVerification: () => data<{ sent: boolean }>(
    client.post('/api/v1/auth/resend-verification'),
  ),
  getSecurityEvents: (limit = 100) => data<AuthSecurityEvent[]>(
    client.get('/api/v1/auth/security-events', { params: { limit } }),
  ),
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
  getWorkspaceSecurityPolicy: () => data<WorkspaceSecurityPolicy>(
    client.get('/api/v1/team/security-policy'),
  ),
  updateWorkspaceSecurityPolicy: (require_mfa: boolean) => data<WorkspaceSecurityPolicy>(
    client.patch('/api/v1/team/security-policy', { require_mfa }),
  ),
  getWorkspaceVerificationPolicy: () => data<WorkspaceVerificationPolicy>(
    client.get('/api/v1/team/verification-policy'),
  ),
  updateWorkspaceVerificationPolicy: (
    payload: WorkspaceVerificationPolicyUpdate,
  ) => data<WorkspaceVerificationPolicy>(
    client.patch('/api/v1/team/verification-policy', payload),
  ),
  getWorkspaceSsoConfig: () => data<WorkspaceSsoConfig | null>(
    client.get('/api/v1/team/sso-config'),
  ),
  updateWorkspaceSsoConfig: (payload: WorkspaceSsoConfigUpdate) => data<WorkspaceSsoConfig>(
    client.put('/api/v1/team/sso-config', payload),
  ),
  updateWorkspaceSsoEnforcement: (enforce_sso: boolean) => data<WorkspaceSsoConfig>(
    client.patch('/api/v1/team/sso-config/enforcement', { enforce_sso }),
  ),
  getWorkspaceScimConfig: () => data<WorkspaceScimConfig>(
    client.get('/api/v1/team/scim-config'),
  ),
  updateWorkspaceScimConfig: (enabled: boolean, default_role: string) => data<WorkspaceScimConfig>(
    client.patch('/api/v1/team/scim-config', { enabled, default_role }),
  ),
  rotateScimToken: () => data<ScimTokenResult>(
    client.post('/api/v1/team/scim-token/rotate'),
  ),
  getScimGroups: () => data<ScimAdminGroup[]>(
    client.get('/api/v1/team/scim-groups'),
  ),
  mapScimGroupRole: (groupId: string, mapped_role: string | null) => data<ScimAdminGroup>(
    client.patch('/api/v1/team/scim-groups/' + groupId, { mapped_role }),
  ),
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
  getMonitorTrend: (
    monitorId: string,
    hours = 168,
    asin?: string,
    geo_profile_id?: string,
  ) => data<AnalyticsTrend>(
    client.get('/api/v1/analytics/monitors/' + monitorId + '/trend', {
      params: { hours, asin, geo_profile_id },
    }),
  ),
  getMonitorAnalyticsSummary: (monitorId: string, hours = 168) => data<AnalyticsSummary>(
    client.get('/api/v1/analytics/monitors/' + monitorId + '/summary', {
      params: { hours },
    }),
  ),
  exportMonitorCsv: (
    monitorId: string,
    hours = 168,
    granularity: 'aggregate' | 'geo' = 'aggregate',
  ) => data<Blob>(
    client.get('/api/v1/analytics/monitors/' + monitorId + '/export.csv', {
      params: { hours, granularity },
      responseType: 'blob',
    }),
  ),
  getCompetitiveSummary: (
    monitorId: string,
    hours = 168,
    top_n = 20,
    limit = 50,
    include_tracked = false,
  ) => data<CompetitiveSummary>(
    client.get('/api/v1/competitive/monitors/' + monitorId + '/summary', {
      params: { hours, top_n, limit, include_tracked },
    }),
  ),
  getCompetitiveTrend: (
    monitorId: string,
    hours = 168,
    top_n = 20,
    asins?: string[],
  ) => data<CompetitiveTrend>(
    client.get('/api/v1/competitive/monitors/' + monitorId + '/trend', {
      params: { hours, top_n, asins },
    }),
  ),
  getReportSchedules: () => data<ReportSchedule[]>(
    client.get('/api/v1/reports/schedules'),
  ),
  createReportSchedule: (payload: ReportSchedulePayload) => data<ReportSchedule>(
    client.post('/api/v1/reports/schedules', payload),
  ),
  updateReportSchedule: (
    id: string,
    payload: Partial<ReportSchedulePayload>,
  ) => data<ReportSchedule>(
    client.patch('/api/v1/reports/schedules/' + id, payload),
  ),
  deleteReportSchedule: (id: string) => data<void>(
    client.delete('/api/v1/reports/schedules/' + id),
  ),
  sendReportNow: (id: string) => data<ReportDelivery>(
    client.post('/api/v1/reports/schedules/' + id + '/send'),
  ),
  getReportDeliveries: (limit = 100) => data<ReportDelivery[]>(
    client.get('/api/v1/reports/deliveries', { params: { limit } }),
  ),
  getAlertRules: () => data<AlertRule[]>(client.get('/api/v1/alerts/rules')),
  createAlertRule: (payload: AlertRulePayload) => data<AlertRule>(
    client.post('/api/v1/alerts/rules', payload),
  ),
  updateAlertRule: (id: string, payload: Partial<AlertRulePayload>) => data<AlertRule>(
    client.patch('/api/v1/alerts/rules/' + id, payload),
  ),
  deleteAlertRule: (id: string) => data<void>(
    client.delete('/api/v1/alerts/rules/' + id),
  ),
  getAlertEvents: (limit = 100) => data<AlertEvent[]>(
    client.get('/api/v1/alerts/events', { params: { limit } }),
  ),
  getMonitors: () => data<Monitor[]>(client.get('/api/v1/monitors')),
  getMonitor: (id: string) => data<Monitor>(client.get('/api/v1/monitors/' + id)),
  createMonitor: (payload: Partial<Monitor>) => data<Monitor>(client.post('/api/v1/monitors', payload)),
  updateMonitor: (id: string, payload: Partial<Monitor>) => data<Monitor>(
    client.patch('/api/v1/monitors/' + id, payload),
  ),
  deleteMonitor: (id: string) => data<void>(client.delete('/api/v1/monitors/' + id)),
  runMonitor: (id: string, force_strict_verification = false) => data<any>(
    client.post('/api/v1/monitors/' + id + '/run', {
      force_strict_verification,
    }),
  ),
  checkRank: (payload: {
    marketplace: string
    keyword: string
    asins: string[]
    geo_profile_ids: string[]
    search_depth: number
    provider_mode: 'managed' | 'strict'
    force_strict_verification?: boolean
  }) => data<RankCheckResult>(client.post('/api/v1/rank/check', payload)),
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
  getVerificationSummary: () => data<VerificationSummary>(
    client.get('/api/v1/system/verification-summary'),
  ),
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
