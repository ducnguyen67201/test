import axios from 'axios'

const API_BASE_URL =
  import.meta.env.VITE_API_URL?.toString().replace(/\/$/, '') ??
  'http://localhost:8000'

const TOKEN_KEY = 'octolab_token'
let accessToken: string | null =
  typeof window !== 'undefined' ? localStorage.getItem(TOKEN_KEY) : null

export const setAccessToken = (token: string | null) => {
  accessToken = token
  if (typeof window === 'undefined') {
    return
  }
  if (token) {
    localStorage.setItem(TOKEN_KEY, token)
  } else {
    localStorage.removeItem(TOKEN_KEY)
  }
}

export const getAccessToken = () => accessToken

export const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
})

api.interceptors.request.use((config) => {
  const token = getAccessToken()
  if (token) {
    config.headers = config.headers ?? {}
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

export interface LoginRequest {
  email: string
  password: string
}

export interface RegisterRequest {
  email: string
  password: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
}

export interface RegisterResponse {
  access_token: string
  token_type: string
  user: UserProfile
}

export interface UserProfile {
  id: string
  email: string
  is_admin: boolean
}

export interface Recipe {
  id: string
  name: string
  description?: string | null
  software?: string | null
  version_constraint?: string | null
  exploit_family?: string | null
}

// Evidence state values matching EvidenceState enum
export type EvidenceState = 'collecting' | 'ready' | 'partial' | 'unavailable'

// Runtime type values matching RuntimeType enum
export type RuntimeType = 'compose' | 'firecracker'

// Runtime metadata (safe subset from server)
export interface RuntimeMeta {
  vm_id?: string | null
  state_dir?: string | null  // basename only, not full path
  firecracker_pid?: number | null
}

export interface Lab {
  id: string
  status: string
  recipe_id: string
  requested_intent?: Record<string, unknown> | null
  connection_url?: string | null
  evidence_state?: EvidenceState | null
  evidence_finalized_at?: string | null
  runtime: RuntimeType  // Server-owned, never from client
  runtime_meta?: RuntimeMeta | null  // Server-owned runtime metadata
}

export const loginRequest = (data: LoginRequest) =>
  api.post<TokenResponse>('/auth/login', data)

export const registerRequest = (data: RegisterRequest) =>
  api.post<RegisterResponse>('/auth/register', data)

export const fetchCurrentUser = () => api.get<UserProfile>('/auth/me')

export const fetchRecipes = async (): Promise<Recipe[]> => {
  const response = await api.get<Recipe[]>('/recipes')
  return response.data
}

export const createLab = async (recipeId: string) => {
  const response = await api.post<Lab>('/labs', {
    recipe_id: recipeId,
    intent: null,
  })
  return response.data
}

export const fetchLabs = async (): Promise<Lab[]> => {
  const response = await api.get<Lab[]>('/labs')
  return response.data
}

export const fetchLab = async (labId: string): Promise<Lab> => {
  const response = await api.get<Lab>(`/labs/${labId}`)
  return response.data
}

export const deleteLab = async (labId: string): Promise<void> => {
  await api.delete(`/labs/${labId}`)
}

export const downloadLabEvidence = async (
  labId: string,
): Promise<{ blob: Blob; filename: string }> => {
  const response = await api.get(`/labs/${labId}/evidence/bundle.zip`, {
    responseType: 'blob',
  })
  const disposition = response.headers['content-disposition'] ?? ''
  const match = disposition.match(/filename="?(.*?)"?$/)
  const filename = match?.[1] ?? `lab_${labId}_evidence.zip`
  return { blob: response.data, filename }
}

export interface LabConnectResponse {
  redirect_url: string
}

export const getLabConnectUrl = async (
  labId: string,
): Promise<LabConnectResponse> => {
  const response = await api.post<LabConnectResponse>(`/labs/${labId}/connect`)
  return response.data
}

// Admin API types and functions
export interface ContainerDebugInfo {
  name: string
  project: string
}

export interface NetworkStatusResponse {
  total_networks: number
  octolab_networks: number
  // Corrected lab-only counts (using compose project labels)
  running_lab_projects: number
  running_lab_containers: number
  running_nonlab_containers: number
  running_total_containers: number
  hint: string
  // Debug sample (admin-only, max 10)
  debug_sample: ContainerDebugInfo[]
}

export interface CleanupNetworksResponse {
  success: boolean
  networks_found: number
  networks_removed: number
  networks_skipped_in_use: number
  containers_found: number
  containers_removed: number
  errors: string[]
  message: string
}

export const fetchNetworkStatus = async (): Promise<NetworkStatusResponse> => {
  const response = await api.get<NetworkStatusResponse>(
    '/admin/maintenance/network-status',
  )
  return response.data
}

export const cleanupNetworks = async (
  removeStoppedContainers: boolean = true,
): Promise<CleanupNetworksResponse> => {
  const response = await api.post<CleanupNetworksResponse>(
    '/admin/maintenance/cleanup-networks',
    {
      confirm: true,
      remove_stopped_containers: removeStoppedContainers,
    },
  )
  return response.data
}

// Network Leak Inspection API types
export interface AttachedContainerSample {
  container: string
  state: 'running' | 'exited' | 'unknown'
  project: string | null
}

export interface NetworkLeakInfo {
  network: string
  attached_containers: number
  attached_running: number
  attached_exited: number
  lab_attached: number
  nonlab_attached: number
  blocked_by_nonlab: boolean
  sample: AttachedContainerSample[]
}

export interface NetworkLeaksResponse {
  total_candidates: number
  detached: number
  in_use: number
  blocked_by_nonlab: number
  networks: NetworkLeakInfo[]
}

export const fetchNetworkLeaks = async (
  debug: boolean = false,
  limit: number = 50,
): Promise<NetworkLeaksResponse> => {
  const response = await api.get<NetworkLeaksResponse>(
    '/admin/maintenance/network-leaks',
    { params: { debug, limit } },
  )
  return response.data
}

// Extended Cleanup API types
export type ExtendedCleanupMode = 'networks_only' | 'remove_exited_lab_containers_then_networks'

export interface SkippedNetworkSample {
  network: string
  reason: string
  sample: AttachedContainerSample[]
}

export interface ExtendedCleanupDebug {
  skipped_samples: SkippedNetworkSample[]
}

export interface ExtendedCleanupResponse {
  mode: string
  networks_found: number
  networks_removed: number
  networks_failed: number
  networks_skipped_in_use_running: number
  networks_skipped_in_use_exited: number
  networks_skipped_blocked_nonlab: number
  containers_removed: number
  message: string
  debug: ExtendedCleanupDebug | null
}

export const cleanupNetworksV2 = async (
  mode: ExtendedCleanupMode,
  confirmPhrase: string,
  debug: boolean = false,
): Promise<ExtendedCleanupResponse> => {
  const response = await api.post<ExtendedCleanupResponse>(
    '/admin/maintenance/cleanup-networks-v2',
    {
      mode,
      confirm: true,
      confirm_phrase: confirmPhrase,
      debug,
    },
  )
  return response.data
}

// Runtime Drift API types and functions
export interface RuntimeProjectInfo {
  project: string
  lab_id: string
  classification: 'tracked' | 'drifted' | 'orphaned'
  db_status: string | null
  container_count: number
  sample_containers: string[]
}

export interface RuntimeDriftDebugSample {
  project: string
  container: string
  db_status: string | null
}

export interface RuntimeDriftResponse {
  scan_id: string  // UUID for this scan, required for stop-labs
  generated_at: string  // ISO8601 timestamp
  running_lab_projects_total: number
  running_lab_containers_total: number
  tracked_running_projects: number
  drifted_running_projects: number
  orphaned_running_projects: number
  projects: RuntimeProjectInfo[]
  debug_sample: RuntimeDriftDebugSample[]
}

export type StopLabsMode = 'orphaned_only' | 'drifted_only' | 'tracked_only' | 'all_running'

// Per-project result with verification data
export interface ProjectStopResultInfo {
  project: string
  pre_running: number
  down_rc: number | null
  remaining_after_down: number
  rm_rc: number | null
  remaining_final: number
  networks_removed: number
  verified_stopped: boolean
  error: string | null
}

export interface StopLabsResponse {
  scan_id: string  // The scan this operation was bound to
  mode: string  // The mode that was used
  targets_requested: number  // Number of projects targeted based on mode
  targets_found: number  // Same as requested for clarity
  before_projects: number  // Running lab projects from scan (before)
  before_containers: number  // Running lab containers from scan (before)
  projects_stopped: number  // Verified: remaining_final == 0
  projects_failed: number  // Verified: remaining_final > 0
  containers_force_removed: number
  networks_removed: number
  networks_failed: number
  after_projects: number  // Running lab projects after execution (fresh query)
  after_containers: number  // Running lab containers after execution (fresh query)
  errors: string[]
  results: ProjectStopResultInfo[]  // Per-project details
  message: string
}

export interface StopProjectResponse {
  project: string
  pre_running: number
  down_rc: number | null
  remaining_after_down: number
  rm_rc: number | null
  remaining_final: number
  stopped: boolean  // True only if remaining_final == 0 (verified)
  networks_removed: number
  error: string | null
}

export const fetchRuntimeDrift = async (
  debug: boolean = false,
): Promise<RuntimeDriftResponse> => {
  const response = await api.get<RuntimeDriftResponse>(
    '/admin/maintenance/runtime-drift',
    { params: { debug } },
  )
  return response.data
}

export const stopLabs = async (
  scanId: string,
  mode: StopLabsMode,
  confirmPhrase: string,
  debug: boolean = false,
): Promise<StopLabsResponse> => {
  const response = await api.post<StopLabsResponse>(
    '/admin/maintenance/stop-labs',
    {
      scan_id: scanId,
      mode,
      confirm: true,
      confirm_phrase: confirmPhrase,
      debug,
    },
  )
  return response.data
}

export const stopProject = async (
  project: string,
): Promise<StopProjectResponse> => {
  const response = await api.post<StopProjectResponse>(
    '/admin/maintenance/stop-project',
    {
      project,
      confirm: true,
    },
  )
  return response.data
}

// =============================================================================
// MicroVM (Firecracker) Admin API
// =============================================================================

export interface DoctorCheckResponse {
  name: string
  ok: boolean
  severity: 'info' | 'warn' | 'fatal'
  details: string
  hint: string
}

export interface DoctorReportResponse {
  ok: boolean
  checks: DoctorCheckResponse[]
  summary: string
  generated_at: string
  fatal_count: number
  warn_count: number
}

export interface RuntimeStatusResponse {
  override: string | null
  effective_runtime: string
  doctor_ok: boolean
  doctor_summary: string
  last_smoke_ok: boolean
  last_smoke_at: string | null
}

export interface RuntimeOverrideRequest {
  override: string | null
}

export interface RuntimeOverrideResponse {
  success: boolean
  message: string
  effective_runtime: string
  doctor_report: DoctorReportResponse | null
}

export interface SmokeTimings {
  boot_ms: number
  ready_ms: number
  teardown_ms: number
  total_ms: number
}

export interface SmokeRequest {
  enable_for_new_labs?: boolean
  mode?: string
}

export interface SmokeResponse {
  ok: boolean
  timings: SmokeTimings | null
  notes: string[]
  doctor_report: DoctorReportResponse | null
  runtime_enabled: boolean
  error: string | null
}

export const fetchRuntimeStatus = async (): Promise<RuntimeStatusResponse> => {
  const response = await api.get<RuntimeStatusResponse>('/admin/runtime')
  return response.data
}

export const setRuntimeOverride = async (
  override: string | null,
): Promise<RuntimeOverrideResponse> => {
  const response = await api.post<RuntimeOverrideResponse>('/admin/runtime', {
    override,
  })
  return response.data
}

export const fetchMicroVMDoctor = async (): Promise<DoctorReportResponse> => {
  const response = await api.get<DoctorReportResponse>('/admin/microvm/doctor')
  return response.data
}

export const runMicroVMSmoke = async (
  enableForNewLabs: boolean = false,
  mode: string = 'serial',
): Promise<SmokeResponse> => {
  const response = await api.post<SmokeResponse>('/admin/microvm/smoke', {
    enable_for_new_labs: enableForNewLabs,
    mode,
  })
  return response.data
}

// =============================================================================
// Firecracker Status API (Admin Only)
// =============================================================================

export interface LabRuntimeStatus {
  lab_id: string
  vm_id: string | null
  firecracker_pid: number | null
  api_sock_exists: boolean
  state_dir_exists: boolean
  status: 'ok' | 'missing_pid' | 'missing_sock' | 'missing_state' | 'unknown'
}

export interface FirecrackerStatusDrift {
  db_running_no_pid: string[]
  orphan_pids: number[]
}

export interface FirecrackerStatusResponse {
  generated_at: string
  firecracker_process_count: number
  running_microvm_labs: LabRuntimeStatus[]
  drift: FirecrackerStatusDrift
  summary: string
}

export const fetchFirecrackerStatus = async (): Promise<FirecrackerStatusResponse> => {
  const response = await api.get<FirecrackerStatusResponse>(
    '/admin/maintenance/firecracker/status',
  )
  return response.data
}

