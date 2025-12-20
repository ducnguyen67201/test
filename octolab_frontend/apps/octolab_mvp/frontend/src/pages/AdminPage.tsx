import { useCallback, useEffect, useState, useMemo } from 'react'
import { Link, Navigate } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import {
  fetchNetworkStatus,
  cleanupNetworks,
  fetchNetworkLeaks,
  cleanupNetworksV2,
  fetchRuntimeDrift,
  stopLabs,
  stopProject,
  fetchRuntimeStatus,
  fetchMicroVMDoctor,
  runMicroVMSmoke,
  setRuntimeOverride,
  fetchFirecrackerStatus,
  type NetworkStatusResponse,
  type CleanupNetworksResponse,
  type NetworkLeaksResponse,
  type ExtendedCleanupResponse,
  type ExtendedCleanupMode,
  type RuntimeDriftResponse,
  type StopLabsResponse,
  type StopLabsMode,
  type StopProjectResponse,
  type RuntimeStatusResponse,
  type DoctorReportResponse,
  type SmokeResponse,
  type FirecrackerStatusResponse,
} from '../api/client'

const STOP_LABS_CONFIRM_PHRASE = 'STOP RUNNING LABS'
const CLEANUP_CONFIRM_PHRASE = 'DELETE OCTOLAB NETWORKS'

export default function AdminPage() {
  const { user, isLoading: authLoading, logout } = useAuth()
  const [networkStatus, setNetworkStatus] = useState<NetworkStatusResponse | null>(null)
  const [statusLoading, setStatusLoading] = useState(false)
  const [statusError, setStatusError] = useState<string | null>(null)
  const [showDebugSample, setShowDebugSample] = useState(false)
  const [cleanupResult, setCleanupResult] = useState<CleanupNetworksResponse | null>(null)
  const [cleanupLoading, setCleanupLoading] = useState(false)
  const [cleanupError, setCleanupError] = useState<string | null>(null)
  const [confirmStep, setConfirmStep] = useState(0)

  // Network Leaks state
  const [networkLeaks, setNetworkLeaks] = useState<NetworkLeaksResponse | null>(null)
  const [leaksLoading, setLeaksLoading] = useState(false)
  const [leaksError, setLeaksError] = useState<string | null>(null)
  const [showLeaksDetails, setShowLeaksDetails] = useState(false)

  // Extended Cleanup state
  const [cleanupMode, setCleanupMode] = useState<ExtendedCleanupMode>('networks_only')
  const [cleanupPhrase, setCleanupPhrase] = useState('')
  const [extendedCleanupResult, setExtendedCleanupResult] = useState<ExtendedCleanupResponse | null>(null)
  const [extendedCleanupLoading, setExtendedCleanupLoading] = useState(false)
  const [extendedCleanupError, setExtendedCleanupError] = useState<string | null>(null)

  // Runtime Drift state
  const [driftData, setDriftData] = useState<RuntimeDriftResponse | null>(null)
  const [driftLoading, setDriftLoading] = useState(false)
  const [driftError, setDriftError] = useState<string | null>(null)
  const [showDriftProjects, setShowDriftProjects] = useState(false)

  // Stop Labs state
  const [stopLabsMode, setStopLabsMode] = useState<StopLabsMode>('all_running')
  const [stopLabsPhrase, setStopLabsPhrase] = useState('')
  const [stopLabsResult, setStopLabsResult] = useState<StopLabsResponse | null>(null)
  const [stopLabsLoading, setStopLabsLoading] = useState(false)
  const [stopLabsError, setStopLabsError] = useState<string | null>(null)

  // Per-project stop state
  const [stoppingProject, setStoppingProject] = useState<string | null>(null)
  const [projectStopResult, setProjectStopResult] = useState<StopProjectResponse | null>(null)
  const [projectStopError, setProjectStopError] = useState<string | null>(null)

  // MicroVM (Firecracker) state
  const [runtimeStatus, setRuntimeStatus] = useState<RuntimeStatusResponse | null>(null)
  const [runtimeLoading, setRuntimeLoading] = useState(false)
  const [runtimeError, setRuntimeError] = useState<string | null>(null)
  const [doctorReport, setDoctorReport] = useState<DoctorReportResponse | null>(null)
  const [doctorLoading, setDoctorLoading] = useState(false)
  const [doctorError, setDoctorError] = useState<string | null>(null)
  const [smokeResult, setSmokeResult] = useState<SmokeResponse | null>(null)
  const [smokeLoading, setSmokeLoading] = useState(false)
  const [smokeError, setSmokeError] = useState<string | null>(null)
  const [showDoctorChecks, setShowDoctorChecks] = useState(false)

  // Firecracker Runtime Status (admin-only)
  const [fcStatus, setFcStatus] = useState<FirecrackerStatusResponse | null>(null)
  const [fcStatusLoading, setFcStatusLoading] = useState(false)
  const [fcStatusError, setFcStatusError] = useState<string | null>(null)
  const [showFcLabs, setShowFcLabs] = useState(false)

  const loadStatus = useCallback(async () => {
    setStatusLoading(true)
    setStatusError(null)
    try {
      const status = await fetchNetworkStatus()
      setNetworkStatus(status)
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to load status'
      setStatusError(message)
    } finally {
      setStatusLoading(false)
    }
  }, [])

  const loadDrift = useCallback(async () => {
    setDriftLoading(true)
    setDriftError(null)
    try {
      const drift = await fetchRuntimeDrift(true)
      setDriftData(drift)
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to load runtime drift'
      setDriftError(message)
    } finally {
      setDriftLoading(false)
    }
  }, [])

  const loadNetworkLeaks = useCallback(async () => {
    setLeaksLoading(true)
    setLeaksError(null)
    try {
      const leaks = await fetchNetworkLeaks(true, 50)
      setNetworkLeaks(leaks)
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to load network leaks'
      setLeaksError(message)
    } finally {
      setLeaksLoading(false)
    }
  }, [])

  const handleExtendedCleanup = useCallback(async () => {
    if (cleanupPhrase !== CLEANUP_CONFIRM_PHRASE) {
      setExtendedCleanupError(`Confirmation phrase must be exactly: ${CLEANUP_CONFIRM_PHRASE}`)
      return
    }

    setExtendedCleanupLoading(true)
    setExtendedCleanupError(null)
    setExtendedCleanupResult(null)
    try {
      const result = await cleanupNetworksV2(cleanupMode, cleanupPhrase, true)
      setExtendedCleanupResult(result)
      setCleanupPhrase('')
      // Refresh status and leaks after cleanup
      await Promise.all([loadStatus(), loadNetworkLeaks()])
    } catch (err: unknown) {
      if (
        err &&
        typeof err === 'object' &&
        'response' in err &&
        err.response &&
        typeof err.response === 'object'
      ) {
        const response = err.response as { status?: number; data?: { detail?: string } }
        if (response.status === 409) {
          setExtendedCleanupError(
            'Cannot cleanup while OctoLab containers are running. Stop all labs first.',
          )
        } else if (response.status === 400) {
          setExtendedCleanupError(response.data?.detail ?? 'Confirmation required')
        } else if (response.status === 403) {
          setExtendedCleanupError('Admin access required.')
        } else {
          setExtendedCleanupError(response.data?.detail ?? 'Cleanup failed')
        }
      } else {
        const message = err instanceof Error ? err.message : 'Cleanup failed'
        setExtendedCleanupError(message)
      }
    } finally {
      setExtendedCleanupLoading(false)
    }
  }, [cleanupMode, cleanupPhrase, loadStatus, loadNetworkLeaks])

  const refreshAll = useCallback(async () => {
    await Promise.all([loadStatus(), loadDrift()])
  }, [loadStatus, loadDrift])

  useEffect(() => {
    if (user?.is_admin) {
      refreshAll()
    }
  }, [user?.is_admin, refreshAll])

  // Smart default mode selection based on what's available
  const recommendedMode = useMemo((): StopLabsMode => {
    if (!driftData) return 'all_running'
    if (driftData.orphaned_running_projects > 0) return 'orphaned_only'
    if (driftData.drifted_running_projects > 0) return 'drifted_only'
    if (driftData.tracked_running_projects > 0) return 'tracked_only'
    return 'all_running'
  }, [driftData])

  // Update mode when recommendation changes (only if user hasn't manually selected)
  useEffect(() => {
    if (driftData && stopLabsMode === 'all_running') {
      setStopLabsMode(recommendedMode)
    }
  }, [recommendedMode, driftData, stopLabsMode])

  const handleCleanup = useCallback(async () => {
    if (confirmStep < 2) {
      setConfirmStep((prev) => prev + 1)
      return
    }

    setCleanupLoading(true)
    setCleanupError(null)
    setCleanupResult(null)
    try {
      const result = await cleanupNetworks(true)
      setCleanupResult(result)
      setConfirmStep(0)
      await refreshAll()
    } catch (err: unknown) {
      if (
        err &&
        typeof err === 'object' &&
        'response' in err &&
        err.response &&
        typeof err.response === 'object' &&
        'status' in err.response
      ) {
        const response = err.response as { status: number; data?: { detail?: string } }
        if (response.status === 409) {
          setCleanupError(
            'Cannot cleanup while OctoLab containers are running. Stop all labs first.',
          )
        } else if (response.status === 403) {
          setCleanupError('Admin access required.')
        } else {
          setCleanupError(response.data?.detail ?? 'Cleanup failed')
        }
      } else {
        const message = err instanceof Error ? err.message : 'Cleanup failed'
        setCleanupError(message)
      }
      setConfirmStep(0)
    } finally {
      setCleanupLoading(false)
    }
  }, [confirmStep, refreshAll])

  const cancelCleanup = useCallback(() => {
    setConfirmStep(0)
  }, [])

  const handleStopLabs = useCallback(async () => {
    if (stopLabsPhrase !== STOP_LABS_CONFIRM_PHRASE) {
      setStopLabsError(`Confirmation phrase must be exactly: ${STOP_LABS_CONFIRM_PHRASE}`)
      return
    }

    if (!driftData?.scan_id) {
      setStopLabsError('No scan available. Please refresh runtime drift first.')
      return
    }

    setStopLabsLoading(true)
    setStopLabsError(null)
    setStopLabsResult(null)
    try {
      const result = await stopLabs(driftData.scan_id, stopLabsMode, stopLabsPhrase)
      setStopLabsResult(result)
      setStopLabsPhrase('')
      await refreshAll()
    } catch (err: unknown) {
      if (
        err &&
        typeof err === 'object' &&
        'response' in err &&
        err.response &&
        typeof err.response === 'object'
      ) {
        const response = err.response as { status?: number; data?: { detail?: string } }
        if (response.status === 409) {
          setStopLabsError('Scan expired. Please refresh runtime drift and try again.')
          await loadDrift()  // Auto-refresh drift data
        } else if (response.status === 400) {
          setStopLabsError(response.data?.detail ?? 'Confirmation required')
        } else if (response.status === 403) {
          setStopLabsError('Admin access required.')
        } else {
          setStopLabsError(response.data?.detail ?? 'Stop labs failed')
        }
      } else {
        const message = err instanceof Error ? err.message : 'Stop labs failed'
        setStopLabsError(message)
      }
    } finally {
      setStopLabsLoading(false)
    }
  }, [stopLabsMode, stopLabsPhrase, driftData?.scan_id, refreshAll, loadDrift])

  const handleStopProject = useCallback(async (projectName: string) => {
    setStoppingProject(projectName)
    setProjectStopResult(null)
    setProjectStopError(null)
    try {
      const result = await stopProject(projectName)
      setProjectStopResult(result)
      // Always refresh to get truthful state, regardless of success/failure
      await refreshAll()
    } catch (err: unknown) {
      if (
        err &&
        typeof err === 'object' &&
        'response' in err &&
        err.response &&
        typeof err.response === 'object'
      ) {
        const response = err.response as { status?: number; data?: { detail?: string } }
        setProjectStopError(response.data?.detail ?? 'Failed to stop project')
      } else {
        const message = err instanceof Error ? err.message : 'Failed to stop project'
        setProjectStopError(message)
      }
      // Also refresh on error to get current state
      await refreshAll()
    } finally {
      setStoppingProject(null)
    }
  }, [refreshAll])

  // MicroVM callbacks
  const loadRuntimeStatus = useCallback(async () => {
    setRuntimeLoading(true)
    setRuntimeError(null)
    try {
      const status = await fetchRuntimeStatus()
      setRuntimeStatus(status)
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to load runtime status'
      setRuntimeError(message)
    } finally {
      setRuntimeLoading(false)
    }
  }, [])

  const loadDoctor = useCallback(async () => {
    setDoctorLoading(true)
    setDoctorError(null)
    try {
      const report = await fetchMicroVMDoctor()
      setDoctorReport(report)
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to run doctor'
      setDoctorError(message)
    } finally {
      setDoctorLoading(false)
    }
  }, [])

  const handleRunSmoke = useCallback(async (enableForNewLabs: boolean = false) => {
    setSmokeLoading(true)
    setSmokeError(null)
    setSmokeResult(null)
    try {
      const result = await runMicroVMSmoke(enableForNewLabs)
      setSmokeResult(result)
      // Also update doctor report from smoke result
      if (result.doctor_report) {
        setDoctorReport(result.doctor_report)
      }
      // Refresh runtime status
      await loadRuntimeStatus()
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Smoke test failed'
      setSmokeError(message)
    } finally {
      setSmokeLoading(false)
    }
  }, [loadRuntimeStatus])

  const handleDisableFirecracker = useCallback(async () => {
    setRuntimeLoading(true)
    setRuntimeError(null)
    try {
      await setRuntimeOverride(null)
      await loadRuntimeStatus()
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to disable Firecracker'
      setRuntimeError(message)
    } finally {
      setRuntimeLoading(false)
    }
  }, [loadRuntimeStatus])

  // Firecracker Status callback
  const loadFirecrackerStatus = useCallback(async () => {
    setFcStatusLoading(true)
    setFcStatusError(null)
    try {
      const status = await fetchFirecrackerStatus()
      setFcStatus(status)
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to load Firecracker status'
      setFcStatusError(message)
    } finally {
      setFcStatusLoading(false)
    }
  }, [])

  if (authLoading) {
    return (
      <div className="page">
        <p>Loading...</p>
      </div>
    )
  }

  if (!user?.is_admin) {
    return <Navigate to="/labs" replace />
  }

  const canStopLabs = stopLabsPhrase === STOP_LABS_CONFIRM_PHRASE && !stopLabsLoading

  // Count targets based on mode
  const getTargetCount = (mode: StopLabsMode): number => {
    if (!driftData) return 0
    switch (mode) {
      case 'orphaned_only':
        return driftData.orphaned_running_projects
      case 'drifted_only':
        return driftData.drifted_running_projects
      case 'tracked_only':
        return driftData.tracked_running_projects
      case 'all_running':
        return driftData.running_lab_projects_total
    }
  }

  const currentTargetCount = getTargetCount(stopLabsMode)
  const hasRunningLabs = (networkStatus?.running_lab_containers ?? 0) > 0

  return (
    <div className="page">
      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h1>Admin Panel</h1>
        <div>
          <span style={{ marginRight: '1rem' }}>{user.email}</span>
          <Link to="/labs" style={{ marginRight: '1rem' }}>
            Labs
          </Link>
          <button onClick={logout}>Logout</button>
        </div>
      </header>

      {/* Network Cleanup Callout */}
      {hasRunningLabs && (
        <div
          style={{
            marginTop: '1rem',
            padding: '1rem',
            background: '#fff3cd',
            border: '1px solid #ffc107',
            borderRadius: '4px',
          }}
        >
          <strong>Network cleanup is blocked</strong> until all running lab projects are stopped.
          Use the <strong>"Stop Running Labs"</strong> section below with <strong>"All Running"</strong> mode
          to stop all {networkStatus?.running_lab_projects} lab project(s) and unblock network cleanup.
        </div>
      )}

      {/* Runtime Drift Section */}
      <section style={{ marginTop: '2rem' }}>
        <h2>Runtime Drift</h2>
        <p style={{ color: '#666', marginBottom: '1rem' }}>
          Scan running lab containers and classify against database state.
          Identifies tracked (DB says running), drifted (DB says stopped),
          and orphaned (no DB row) projects.
        </p>

        {driftLoading && <p>Loading runtime drift...</p>}
        {driftError && <p style={{ color: 'red' }}>Error: {driftError}</p>}

        {driftData && (
          <div
            style={{
              background: '#f5f5f5',
              padding: '1rem',
              borderRadius: '4px',
              fontFamily: 'monospace',
            }}
          >
            {/* Scan metadata */}
            <div style={{ marginBottom: '0.5rem', fontSize: '0.85em', color: '#666' }}>
              <span>Scan ID: {driftData.scan_id.substring(0, 8)}...</span>
              <span style={{ marginLeft: '1rem' }}>
                Generated: {new Date(driftData.generated_at).toLocaleTimeString()}
              </span>
              <span style={{ marginLeft: '1rem', color: '#c80' }}>
                (Expires in ~60s - refresh before stop)
              </span>
            </div>
            <p>
              <strong>Running Lab Projects:</strong> {driftData.running_lab_projects_total}
              {' '}({driftData.running_lab_containers_total} containers)
            </p>
            <div style={{ marginTop: '0.5rem', display: 'flex', gap: '2rem' }}>
              <span style={{ color: driftData.tracked_running_projects > 0 ? '#080' : '#666' }}>
                Tracked: {driftData.tracked_running_projects}
              </span>
              <span style={{ color: driftData.drifted_running_projects > 0 ? '#c80' : '#666' }}>
                Drifted: {driftData.drifted_running_projects}
              </span>
              <span style={{ color: driftData.orphaned_running_projects > 0 ? '#c00' : '#666' }}>
                Orphaned: {driftData.orphaned_running_projects}
              </span>
            </div>

            {driftData.projects.length > 0 && (
              <div style={{ marginTop: '0.5rem' }}>
                <button
                  onClick={() => setShowDriftProjects(!showDriftProjects)}
                  style={{ fontSize: '0.9em', padding: '0.25rem 0.5rem' }}
                >
                  {showDriftProjects ? 'Hide' : 'Show'} Projects ({driftData.projects.length})
                </button>
                {showDriftProjects && (
                  <>
                    {projectStopResult && (
                      <div
                        style={{
                          marginTop: '0.5rem',
                          padding: '0.5rem',
                          background: projectStopResult.stopped ? '#d4edda' : '#f8d7da',
                          borderRadius: '4px',
                          fontSize: '0.85em',
                        }}
                      >
                        {projectStopResult.stopped ? (
                          <>
                            <span style={{ color: '#155724' }}>✓ Verified stopped:</span> {projectStopResult.project.substring(0, 40)}...
                            <br />
                            <span style={{ color: '#666' }}>
                              Pre: {projectStopResult.pre_running} → After down: {projectStopResult.remaining_after_down} → Final: {projectStopResult.remaining_final}
                              {projectStopResult.networks_removed > 0 && `, Networks removed: ${projectStopResult.networks_removed}`}
                            </span>
                          </>
                        ) : (
                          <>
                            <span style={{ color: '#721c24' }}>✗ Failed to stop:</span> {projectStopResult.project.substring(0, 40)}...
                            <br />
                            <span style={{ color: '#721c24' }}>
                              Pre: {projectStopResult.pre_running} → After down: {projectStopResult.remaining_after_down} →
                              <strong> Final: {projectStopResult.remaining_final} still running</strong>
                            </span>
                            {projectStopResult.error && <><br /><span style={{ color: '#c00' }}>Error: {projectStopResult.error}</span></>}
                          </>
                        )}
                      </div>
                    )}
                    {projectStopError && (
                      <div
                        style={{
                          marginTop: '0.5rem',
                          padding: '0.5rem',
                          background: '#f8d7da',
                          borderRadius: '4px',
                          fontSize: '0.85em',
                        }}
                      >
                        Error: {projectStopError}
                      </div>
                    )}
                    <table style={{ marginTop: '0.5rem', fontSize: '0.85em', width: '100%' }}>
                      <thead>
                        <tr style={{ textAlign: 'left' }}>
                          <th>Project</th>
                          <th>Classification</th>
                          <th>DB Status</th>
                          <th>Containers</th>
                          <th>Action</th>
                        </tr>
                      </thead>
                      <tbody>
                        {driftData.projects.map((project, i) => (
                          <tr
                            key={i}
                            style={{
                              background:
                                project.classification === 'orphaned'
                                  ? '#fee'
                                  : project.classification === 'drifted'
                                    ? '#ffc'
                                    : 'transparent',
                            }}
                          >
                            <td>
                              <code style={{ fontSize: '0.9em' }}>{project.project.substring(0, 44)}...</code>
                            </td>
                            <td>
                              <span
                                style={{
                                  color:
                                    project.classification === 'orphaned'
                                      ? '#c00'
                                      : project.classification === 'drifted'
                                        ? '#c80'
                                        : '#080',
                                }}
                              >
                                {project.classification}
                              </span>
                            </td>
                            <td>{project.db_status ?? '(none)'}</td>
                            <td>{project.container_count}</td>
                            <td>
                              <button
                                onClick={() => handleStopProject(project.project)}
                                disabled={stoppingProject === project.project}
                                style={{
                                  padding: '0.2rem 0.5rem',
                                  fontSize: '0.85em',
                                  background: '#dc3545',
                                  color: 'white',
                                  border: 'none',
                                  borderRadius: '3px',
                                  cursor: stoppingProject === project.project ? 'wait' : 'pointer',
                                }}
                              >
                                {stoppingProject === project.project ? 'Stopping...' : 'Stop'}
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </>
                )}
              </div>
            )}
          </div>
        )}

        <button
          onClick={loadDrift}
          disabled={driftLoading}
          style={{ marginTop: '1rem' }}
        >
          {driftLoading ? 'Refreshing...' : 'Refresh Drift'}
        </button>
      </section>

      {/* Stop Labs Section - Always show if there are any running labs */}
      {driftData && driftData.running_lab_projects_total > 0 && (
        <section style={{ marginTop: '2rem' }}>
          <h2>Stop Running Labs</h2>
          <p style={{ color: '#666', marginBottom: '1rem' }}>
            Stop lab projects that are running. This frees Docker networks
            and container resources. After stopping all labs, network cleanup becomes available.
          </p>

          <div style={{ marginBottom: '1rem' }}>
            <label style={{ display: 'block', marginBottom: '0.5rem' }}>
              <strong>Mode:</strong>
            </label>
            <select
              value={stopLabsMode}
              onChange={(e) => setStopLabsMode(e.target.value as StopLabsMode)}
              style={{ marginRight: '1rem', padding: '0.5rem', minWidth: '300px' }}
            >
              <option value="orphaned_only">
                Orphaned Only ({driftData.orphaned_running_projects} projects)
                {recommendedMode === 'orphaned_only' ? ' - Recommended' : ''}
              </option>
              <option value="drifted_only">
                Drifted Only ({driftData.drifted_running_projects} projects)
                {recommendedMode === 'drifted_only' ? ' - Recommended' : ''}
              </option>
              <option value="tracked_only">
                Tracked Only ({driftData.tracked_running_projects} projects)
                {recommendedMode === 'tracked_only' ? ' - Recommended' : ''}
              </option>
              <option value="all_running">
                All Running ({driftData.running_lab_projects_total} projects)
              </option>
            </select>
          </div>

          <div style={{ marginBottom: '1rem' }}>
            <label style={{ display: 'block', marginBottom: '0.5rem' }}>
              <strong>Confirmation:</strong> Type exactly: <code>{STOP_LABS_CONFIRM_PHRASE}</code>
            </label>
            <input
              type="text"
              value={stopLabsPhrase}
              onChange={(e) => setStopLabsPhrase(e.target.value)}
              placeholder={STOP_LABS_CONFIRM_PHRASE}
              style={{
                width: '300px',
                padding: '0.5rem',
                fontFamily: 'monospace',
                border: stopLabsPhrase === STOP_LABS_CONFIRM_PHRASE ? '2px solid #080' : '1px solid #ccc',
              }}
            />
          </div>

          {stopLabsError && (
            <div
              style={{
                background: '#fee',
                border: '1px solid #c00',
                padding: '1rem',
                borderRadius: '4px',
                marginBottom: '1rem',
              }}
            >
              <strong>Error:</strong> {stopLabsError}
            </div>
          )}

          {stopLabsResult && (
            <div
              style={{
                background: stopLabsResult.projects_failed === 0 ? '#efe' : '#f8d7da',
                border: `1px solid ${stopLabsResult.projects_failed === 0 ? '#0c0' : '#dc3545'}`,
                padding: '1rem',
                borderRadius: '4px',
                marginBottom: '1rem',
              }}
            >
              {/* Mismatch Banner: if after count doesn't match expected */}
              {(() => {
                const expectedAfter = stopLabsResult.before_projects - stopLabsResult.projects_stopped
                const actualAfter = stopLabsResult.after_projects
                const mismatch = actualAfter !== expectedAfter && stopLabsResult.projects_stopped > 0
                if (mismatch) {
                  return (
                    <div
                      style={{
                        background: '#fff3cd',
                        border: '1px solid #ffc107',
                        padding: '0.5rem',
                        borderRadius: '4px',
                        marginBottom: '0.5rem',
                      }}
                    >
                      <strong>Warning:</strong> Count mismatch detected.
                      Expected {expectedAfter} projects after, but found {actualAfter}.
                      This may indicate concurrent lab activity.
                    </div>
                  )
                }
                return null
              })()}

              <p><strong>Result:</strong> {stopLabsResult.message}</p>

              {/* Before/After Runtime Counts */}
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(2, 1fr)',
                  gap: '0.5rem',
                  marginTop: '0.5rem',
                  padding: '0.5rem',
                  background: '#f8f9fa',
                  borderRadius: '4px',
                }}
              >
                <div>
                  <strong>Before:</strong> {stopLabsResult.before_projects} projects
                  ({stopLabsResult.before_containers} containers)
                </div>
                <div>
                  <strong>After:</strong> {stopLabsResult.after_projects} projects
                  ({stopLabsResult.after_containers} containers)
                </div>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, auto)', gap: '0.5rem 2rem', marginTop: '0.5rem' }}>
                <span>Requested: {stopLabsResult.targets_requested} ({stopLabsResult.mode})</span>
                <span style={{ color: '#080' }}>Verified stopped: {stopLabsResult.projects_stopped}</span>
                <span style={{ color: stopLabsResult.projects_failed > 0 ? '#c00' : '#666' }}>
                  Failed: {stopLabsResult.projects_failed}
                </span>
                <span>Networks removed: {stopLabsResult.networks_removed}</span>
                {stopLabsResult.containers_force_removed > 0 && (
                  <span style={{ color: '#c80' }}>Force-removed: {stopLabsResult.containers_force_removed} containers</span>
                )}
              </div>

              {/* Show per-project failures */}
              {stopLabsResult.results.filter(r => !r.verified_stopped).length > 0 && (
                <div style={{ marginTop: '1rem' }}>
                  <strong style={{ color: '#c00' }}>Failed Projects (containers still running):</strong>
                  <table style={{ marginTop: '0.5rem', fontSize: '0.85em', width: '100%', borderCollapse: 'collapse' }}>
                    <thead>
                      <tr style={{ textAlign: 'left', borderBottom: '1px solid #ddd' }}>
                        <th style={{ padding: '0.25rem' }}>Project</th>
                        <th style={{ padding: '0.25rem' }}>Pre</th>
                        <th style={{ padding: '0.25rem' }}>After Down</th>
                        <th style={{ padding: '0.25rem' }}>Final</th>
                        <th style={{ padding: '0.25rem' }}>Error</th>
                      </tr>
                    </thead>
                    <tbody>
                      {stopLabsResult.results.filter(r => !r.verified_stopped).map((result, i) => (
                        <tr key={i} style={{ background: '#fee' }}>
                          <td style={{ padding: '0.25rem' }}>
                            <code style={{ fontSize: '0.9em' }}>{result.project.substring(0, 44)}...</code>
                          </td>
                          <td style={{ padding: '0.25rem' }}>{result.pre_running}</td>
                          <td style={{ padding: '0.25rem' }}>{result.remaining_after_down}</td>
                          <td style={{ padding: '0.25rem', fontWeight: 'bold', color: '#c00' }}>
                            {result.remaining_final}
                          </td>
                          <td style={{ padding: '0.25rem', color: '#c00' }}>
                            {result.error ?? 'Unknown'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {stopLabsResult.errors.length > 0 && (
                <div style={{ marginTop: '0.5rem' }}>
                  <strong>Errors:</strong>
                  <ul>
                    {stopLabsResult.errors.map((err, i) => (
                      <li key={i}>{err}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}

          <button
            onClick={handleStopLabs}
            disabled={!canStopLabs || currentTargetCount === 0}
            style={{
              background: canStopLabs && currentTargetCount > 0 ? '#c00' : '#ccc',
              color: 'white',
              padding: '0.5rem 1rem',
              fontSize: '1rem',
            }}
          >
            {stopLabsLoading
              ? 'Stopping...'
              : `Stop ${currentTargetCount} ${stopLabsMode.replace(/_/g, ' ')} project(s)`}
          </button>
        </section>
      )}

      {/* Network Status Section */}
      <section style={{ marginTop: '2rem' }}>
        <h2>Network Status</h2>
        {statusLoading && <p>Loading status...</p>}
        {statusError && <p style={{ color: 'red' }}>Error: {statusError}</p>}
        {networkStatus && (
          <div
            style={{
              background: '#f5f5f5',
              padding: '1rem',
              borderRadius: '4px',
              fontFamily: 'monospace',
            }}
          >
            <p>
              <strong>Total Docker Networks:</strong> {networkStatus.total_networks}
            </p>
            <p>
              <strong>OctoLab Lab Networks:</strong> {networkStatus.octolab_networks}
            </p>
            <p style={{ marginTop: '0.5rem', borderTop: '1px solid #ddd', paddingTop: '0.5rem' }}>
              <strong>Running Lab Containers:</strong>{' '}
              {networkStatus.running_lab_containers}
              {' '}(in {networkStatus.running_lab_projects} lab projects)
            </p>
            <p>
              <strong>Running Non-Lab Containers:</strong>{' '}
              {networkStatus.running_nonlab_containers}
              {' '}(infrastructure: guacamole, postgres, etc.)
            </p>
            <p>
              <strong>Running Total Containers:</strong>{' '}
              {networkStatus.running_total_containers}
            </p>
            <p style={{ marginTop: '0.5rem', borderTop: '1px solid #ddd', paddingTop: '0.5rem' }}>
              <strong>Hint:</strong> {networkStatus.hint}
            </p>
            {networkStatus.debug_sample.length > 0 && (
              <div style={{ marginTop: '0.5rem' }}>
                <button
                  onClick={() => setShowDebugSample(!showDebugSample)}
                  style={{ fontSize: '0.9em', padding: '0.25rem 0.5rem' }}
                >
                  {showDebugSample ? 'Hide' : 'Show'} Debug Sample ({networkStatus.debug_sample.length})
                </button>
                {showDebugSample && (
                  <ul style={{ marginTop: '0.5rem', fontSize: '0.85em' }}>
                    {networkStatus.debug_sample.map((container, i) => (
                      <li key={i}>
                        <code>{container.name}</code> → project: <code>{container.project}</code>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </div>
        )}
        <button
          onClick={loadStatus}
          disabled={statusLoading}
          style={{ marginTop: '1rem' }}
        >
          {statusLoading ? 'Refreshing...' : 'Refresh Status'}
        </button>
      </section>

      {/* Network Leaks Inspector Section */}
      <section style={{ marginTop: '2rem' }}>
        <h2>Network Leaks Inspector</h2>
        <p style={{ color: '#666', marginBottom: '1rem' }}>
          Inspect WHY networks are "in use" by showing attached containers and their states.
          Use this to understand if networks are blocked by exited lab containers or nonlab containers.
        </p>

        {leaksLoading && <p>Loading network leaks...</p>}
        {leaksError && <p style={{ color: 'red' }}>Error: {leaksError}</p>}

        {networkLeaks && (
          <div
            style={{
              background: '#f5f5f5',
              padding: '1rem',
              borderRadius: '4px',
              fontFamily: 'monospace',
            }}
          >
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, auto)', gap: '0.5rem 2rem' }}>
              <span><strong>Total Networks:</strong> {networkLeaks.total_candidates}</span>
              <span style={{ color: '#080' }}><strong>Detached:</strong> {networkLeaks.detached} (removable)</span>
              <span style={{ color: networkLeaks.in_use > 0 ? '#c80' : '#666' }}>
                <strong>In Use:</strong> {networkLeaks.in_use}
              </span>
              <span style={{ color: networkLeaks.blocked_by_nonlab > 0 ? '#c00' : '#666' }}>
                <strong>Blocked by Nonlab:</strong> {networkLeaks.blocked_by_nonlab}
              </span>
            </div>

            {networkLeaks.networks.length > 0 && (
              <div style={{ marginTop: '0.5rem' }}>
                <button
                  onClick={() => setShowLeaksDetails(!showLeaksDetails)}
                  style={{ fontSize: '0.9em', padding: '0.25rem 0.5rem' }}
                >
                  {showLeaksDetails ? 'Hide' : 'Show'} In-Use Networks ({networkLeaks.networks.length})
                </button>
                {showLeaksDetails && (
                  <table style={{ marginTop: '0.5rem', fontSize: '0.85em', width: '100%', borderCollapse: 'collapse' }}>
                    <thead>
                      <tr style={{ textAlign: 'left', borderBottom: '1px solid #ddd' }}>
                        <th style={{ padding: '0.25rem' }}>Network</th>
                        <th style={{ padding: '0.25rem' }}>Attached</th>
                        <th style={{ padding: '0.25rem' }}>Running</th>
                        <th style={{ padding: '0.25rem' }}>Exited</th>
                        <th style={{ padding: '0.25rem' }}>Lab</th>
                        <th style={{ padding: '0.25rem' }}>Nonlab</th>
                        <th style={{ padding: '0.25rem' }}>Sample Containers</th>
                      </tr>
                    </thead>
                    <tbody>
                      {networkLeaks.networks.map((net, i) => (
                        <tr
                          key={i}
                          style={{
                            background: net.blocked_by_nonlab
                              ? '#fee'
                              : net.attached_running > 0
                                ? '#ffc'
                                : 'transparent',
                          }}
                        >
                          <td style={{ padding: '0.25rem' }}>
                            <code style={{ fontSize: '0.9em' }}>{net.network.substring(0, 40)}...</code>
                          </td>
                          <td style={{ padding: '0.25rem' }}>{net.attached_containers}</td>
                          <td style={{ padding: '0.25rem', color: net.attached_running > 0 ? '#c00' : '#666' }}>
                            {net.attached_running}
                          </td>
                          <td style={{ padding: '0.25rem', color: net.attached_exited > 0 ? '#c80' : '#666' }}>
                            {net.attached_exited}
                          </td>
                          <td style={{ padding: '0.25rem' }}>{net.lab_attached}</td>
                          <td style={{ padding: '0.25rem', color: net.nonlab_attached > 0 ? '#c00' : '#666' }}>
                            {net.nonlab_attached}
                          </td>
                          <td style={{ padding: '0.25rem', fontSize: '0.85em' }}>
                            {net.sample.map((c, j) => (
                              <div key={j}>
                                <code>{c.container.substring(0, 25)}</code>
                                <span style={{
                                  color: c.state === 'running' ? '#c00' : '#666',
                                  marginLeft: '0.25rem',
                                }}>
                                  ({c.state})
                                </span>
                                {c.project && <span style={{ color: '#666' }}> p:{c.project.substring(0, 20)}</span>}
                              </div>
                            ))}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            )}

            {/* Hints based on leak analysis */}
            {networkLeaks.in_use > 0 && networkLeaks.blocked_by_nonlab === 0 && networkLeaks.detached === 0 && (
              <div style={{ marginTop: '0.5rem', padding: '0.5rem', background: '#fff3cd', borderRadius: '4px' }}>
                <strong>Hint:</strong> Networks are held by exited lab containers.
                Use "Remove exited lab containers then networks" mode below to clean up.
              </div>
            )}
            {networkLeaks.blocked_by_nonlab > 0 && (
              <div style={{ marginTop: '0.5rem', padding: '0.5rem', background: '#f8d7da', borderRadius: '4px' }}>
                <strong>Warning:</strong> {networkLeaks.blocked_by_nonlab} network(s) have nonlab containers attached.
                These cannot be cleaned up automatically. This may indicate a configuration issue.
              </div>
            )}
          </div>
        )}

        <button
          onClick={loadNetworkLeaks}
          disabled={leaksLoading}
          style={{ marginTop: '1rem' }}
        >
          {leaksLoading ? 'Inspecting...' : 'Inspect Network Leaks'}
        </button>
      </section>

      {/* Network Cleanup Section */}
      <section style={{ marginTop: '2rem' }}>
        <h2>Network Cleanup</h2>
        <p style={{ color: '#666', marginBottom: '1rem' }}>
          Clean up leaked OctoLab networks to recover from Docker IPAM exhaustion. This
          removes empty lab networks (no attached containers) to free subnet allocations.
        </p>

        {hasRunningLabs && (
          <div
            style={{
              background: '#fff3cd',
              border: '1px solid #ffc107',
              padding: '1rem',
              borderRadius: '4px',
              marginBottom: '1rem',
            }}
          >
            <strong>Blocked:</strong> {networkStatus?.running_lab_containers} running lab
            containers detected (in {networkStatus?.running_lab_projects} projects).
            Use "Stop Running Labs" above with "All Running" mode to unblock.
          </div>
        )}

        {!hasRunningLabs && networkStatus && networkStatus.octolab_networks > 0 && (
          <div
            style={{
              background: '#d4edda',
              border: '1px solid #28a745',
              padding: '1rem',
              borderRadius: '4px',
              marginBottom: '1rem',
            }}
          >
            <strong>Ready:</strong> No running lab containers. Network cleanup is available.
            Found {networkStatus.octolab_networks} lab networks that can be cleaned up.
          </div>
        )}

        {cleanupError && (
          <div
            style={{
              background: '#fee',
              border: '1px solid #c00',
              padding: '1rem',
              borderRadius: '4px',
              marginBottom: '1rem',
            }}
          >
            <strong>Error:</strong> {cleanupError}
          </div>
        )}

        {cleanupResult && (
          <div
            style={{
              background: cleanupResult.success ? '#efe' : '#ffe',
              border: `1px solid ${cleanupResult.success ? '#0c0' : '#cc0'}`,
              padding: '1rem',
              borderRadius: '4px',
              marginBottom: '1rem',
            }}
          >
            <p>
              <strong>Result:</strong> {cleanupResult.message}
            </p>
            <p>Networks found: {cleanupResult.networks_found}</p>
            <p>Networks removed: {cleanupResult.networks_removed}</p>
            <p>Networks skipped (in use): {cleanupResult.networks_skipped_in_use}</p>
            <p>Containers removed: {cleanupResult.containers_removed}</p>
            {cleanupResult.errors.length > 0 && (
              <div style={{ marginTop: '0.5rem' }}>
                <strong>Errors:</strong>
                <ul>
                  {cleanupResult.errors.map((err, i) => (
                    <li key={i}>{err}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        <div style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
          {confirmStep === 0 && (
            <button
              onClick={handleCleanup}
              disabled={cleanupLoading || hasRunningLabs}
              style={{
                background: hasRunningLabs ? '#ccc' : '#c00',
                color: 'white',
              }}
            >
              Clean Up Networks
            </button>
          )}
          {confirmStep === 1 && (
            <>
              <span style={{ color: '#c00' }}>Are you sure?</span>
              <button
                onClick={handleCleanup}
                style={{ background: '#c00', color: 'white' }}
              >
                Yes, I understand
              </button>
              <button onClick={cancelCleanup}>Cancel</button>
            </>
          )}
          {confirmStep === 2 && (
            <>
              <span style={{ color: '#c00', fontWeight: 'bold' }}>
                Final confirmation - this will delete networks!
              </span>
              <button
                onClick={handleCleanup}
                disabled={cleanupLoading}
                style={{ background: '#800', color: 'white' }}
              >
                {cleanupLoading ? 'Cleaning...' : 'CONFIRM CLEANUP'}
              </button>
              <button onClick={cancelCleanup} disabled={cleanupLoading}>
                Cancel
              </button>
            </>
          )}
        </div>

        {/* Extended Cleanup with Mode Selection */}
        <div style={{ marginTop: '2rem', padding: '1rem', background: '#f8f9fa', borderRadius: '4px' }}>
          <h3 style={{ marginTop: 0 }}>Extended Cleanup (with Mode Selection)</h3>
          <p style={{ color: '#666', marginBottom: '1rem' }}>
            Advanced cleanup with explicit mode selection. Use this when networks are held by exited lab containers.
          </p>

          <div style={{ marginBottom: '1rem' }}>
            <label style={{ display: 'block', marginBottom: '0.5rem' }}>
              <strong>Mode:</strong>
            </label>
            <select
              value={cleanupMode}
              onChange={(e) => setCleanupMode(e.target.value as ExtendedCleanupMode)}
              style={{ marginRight: '1rem', padding: '0.5rem', minWidth: '400px' }}
            >
              <option value="networks_only">
                Networks only (safe) - Only remove detached networks
              </option>
              <option value="remove_exited_lab_containers_then_networks">
                Remove exited lab containers then networks (requires extra confirmation)
              </option>
            </select>
          </div>

          {cleanupMode === 'remove_exited_lab_containers_then_networks' && (
            <div
              style={{
                background: '#fff3cd',
                border: '1px solid #ffc107',
                padding: '1rem',
                borderRadius: '4px',
                marginBottom: '1rem',
              }}
            >
              <strong>Warning:</strong> This mode will delete exited lab containers that are keeping
              networks attached. This cannot be undone. Nonlab containers will never be touched.
            </div>
          )}

          <div style={{ marginBottom: '1rem' }}>
            <label style={{ display: 'block', marginBottom: '0.5rem' }}>
              <strong>Confirmation:</strong> Type exactly: <code>{CLEANUP_CONFIRM_PHRASE}</code>
            </label>
            <input
              type="text"
              value={cleanupPhrase}
              onChange={(e) => setCleanupPhrase(e.target.value)}
              placeholder={CLEANUP_CONFIRM_PHRASE}
              style={{
                width: '300px',
                padding: '0.5rem',
                fontFamily: 'monospace',
                border: cleanupPhrase === CLEANUP_CONFIRM_PHRASE ? '2px solid #080' : '1px solid #ccc',
              }}
            />
          </div>

          {extendedCleanupError && (
            <div
              style={{
                background: '#fee',
                border: '1px solid #c00',
                padding: '1rem',
                borderRadius: '4px',
                marginBottom: '1rem',
              }}
            >
              <strong>Error:</strong> {extendedCleanupError}
            </div>
          )}

          {extendedCleanupResult && (
            <div
              style={{
                background: extendedCleanupResult.networks_removed > 0 ? '#efe' : '#ffe',
                border: `1px solid ${extendedCleanupResult.networks_removed > 0 ? '#0c0' : '#cc0'}`,
                padding: '1rem',
                borderRadius: '4px',
                marginBottom: '1rem',
              }}
            >
              <p><strong>Result:</strong> {extendedCleanupResult.message}</p>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, auto)', gap: '0.5rem 2rem', marginTop: '0.5rem' }}>
                <span>Mode: {extendedCleanupResult.mode}</span>
                <span>Networks found: {extendedCleanupResult.networks_found}</span>
                <span style={{ color: '#080' }}>Networks removed: {extendedCleanupResult.networks_removed}</span>
                <span style={{ color: extendedCleanupResult.networks_skipped_in_use_running > 0 ? '#c00' : '#666' }}>
                  Skipped (running): {extendedCleanupResult.networks_skipped_in_use_running}
                </span>
                <span style={{ color: extendedCleanupResult.networks_skipped_in_use_exited > 0 ? '#c80' : '#666' }}>
                  Skipped (exited): {extendedCleanupResult.networks_skipped_in_use_exited}
                </span>
                <span style={{ color: extendedCleanupResult.networks_skipped_blocked_nonlab > 0 ? '#c00' : '#666' }}>
                  Blocked (nonlab): {extendedCleanupResult.networks_skipped_blocked_nonlab}
                </span>
                <span>Containers removed: {extendedCleanupResult.containers_removed}</span>
              </div>

              {/* Show debug samples if available */}
              {extendedCleanupResult.debug?.skipped_samples && extendedCleanupResult.debug.skipped_samples.length > 0 && (
                <div style={{ marginTop: '0.5rem' }}>
                  <strong>Skipped networks:</strong>
                  <ul style={{ margin: '0.25rem 0', paddingLeft: '1.5rem', fontSize: '0.85em' }}>
                    {extendedCleanupResult.debug.skipped_samples.slice(0, 5).map((s, i) => (
                      <li key={i}>
                        <code>{s.network.substring(0, 40)}...</code>
                        <span style={{ marginLeft: '0.5rem', color: '#666' }}>({s.reason})</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}

          <button
            onClick={handleExtendedCleanup}
            disabled={cleanupPhrase !== CLEANUP_CONFIRM_PHRASE || extendedCleanupLoading || hasRunningLabs}
            style={{
              background: cleanupPhrase === CLEANUP_CONFIRM_PHRASE && !hasRunningLabs ? '#c00' : '#ccc',
              color: 'white',
              padding: '0.5rem 1rem',
              fontSize: '1rem',
            }}
          >
            {extendedCleanupLoading
              ? 'Cleaning...'
              : `Run Extended Cleanup (${cleanupMode.replace(/_/g, ' ')})`}
          </button>
        </div>
      </section>

      {/* MicroVM (Firecracker) Section */}
      <section style={{ marginTop: '2rem' }}>
        <h2>MicroVM (Firecracker)</h2>
        <p style={{ color: '#666', marginBottom: '1rem' }}>
          Firecracker microVM runtime for isolated lab environments. Use doctor to check prerequisites,
          smoke test to verify boot, and enable for new labs.
        </p>

        {/* Runtime Status */}
        <div
          style={{
            background: '#f5f5f5',
            padding: '1rem',
            borderRadius: '4px',
            marginBottom: '1rem',
          }}
        >
          <h3 style={{ marginTop: 0 }}>Runtime Status</h3>
          {runtimeLoading && <p>Loading runtime status...</p>}
          {runtimeError && <p style={{ color: 'red' }}>Error: {runtimeError}</p>}

          {runtimeStatus && (
            <div style={{ fontFamily: 'monospace' }}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '0.5rem' }}>
                <span>
                  <strong>Effective Runtime:</strong>{' '}
                  <span
                    style={{
                      color: runtimeStatus.effective_runtime === 'firecracker' ? '#080' : '#666',
                      fontWeight: 'bold',
                    }}
                  >
                    {runtimeStatus.effective_runtime}
                  </span>
                </span>
                <span>
                  <strong>Override:</strong>{' '}
                  {runtimeStatus.override ?? '(none - default)'}
                </span>
                <span>
                  <strong>Doctor OK:</strong>{' '}
                  <span style={{ color: runtimeStatus.doctor_ok ? '#080' : '#c00' }}>
                    {runtimeStatus.doctor_ok ? 'Yes' : 'No'}
                  </span>
                </span>
                <span>
                  <strong>Last Smoke:</strong>{' '}
                  {runtimeStatus.last_smoke_at
                    ? `${runtimeStatus.last_smoke_ok ? 'Passed' : 'Failed'} at ${new Date(runtimeStatus.last_smoke_at).toLocaleTimeString()}`
                    : 'Never'}
                </span>
              </div>
              <p style={{ marginTop: '0.5rem', color: '#666' }}>
                {runtimeStatus.doctor_summary}
              </p>
            </div>
          )}

          <button
            onClick={loadRuntimeStatus}
            disabled={runtimeLoading}
            style={{ marginTop: '0.5rem' }}
          >
            {runtimeLoading ? 'Refreshing...' : 'Refresh Status'}
          </button>
        </div>

        {/* Doctor Checks */}
        <div
          style={{
            background: '#f5f5f5',
            padding: '1rem',
            borderRadius: '4px',
            marginBottom: '1rem',
          }}
        >
          <h3 style={{ marginTop: 0 }}>Doctor Checks</h3>
          {doctorLoading && <p>Running doctor checks...</p>}
          {doctorError && <p style={{ color: 'red' }}>Error: {doctorError}</p>}

          {doctorReport && (
            <div>
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '1rem',
                  marginBottom: '0.5rem',
                }}
              >
                <span
                  style={{
                    color: doctorReport.ok ? '#080' : '#c00',
                    fontWeight: 'bold',
                    fontSize: '1.1em',
                  }}
                >
                  {doctorReport.ok ? 'READY' : 'NOT READY'}
                </span>
                {doctorReport.fatal_count > 0 && (
                  <span style={{ color: '#c00' }}>
                    {doctorReport.fatal_count} fatal
                  </span>
                )}
                {doctorReport.warn_count > 0 && (
                  <span style={{ color: '#c80' }}>
                    {doctorReport.warn_count} warning(s)
                  </span>
                )}
              </div>
              <p style={{ margin: '0.5rem 0', fontFamily: 'monospace' }}>
                {doctorReport.summary}
              </p>

              <button
                onClick={() => setShowDoctorChecks(!showDoctorChecks)}
                style={{ fontSize: '0.9em', padding: '0.25rem 0.5rem', marginTop: '0.5rem' }}
              >
                {showDoctorChecks ? 'Hide' : 'Show'} Checks ({doctorReport.checks.length})
              </button>

              {showDoctorChecks && (
                <table
                  style={{
                    marginTop: '0.5rem',
                    fontSize: '0.85em',
                    width: '100%',
                    borderCollapse: 'collapse',
                  }}
                >
                  <thead>
                    <tr style={{ textAlign: 'left', borderBottom: '1px solid #ddd' }}>
                      <th style={{ padding: '0.25rem' }}>Check</th>
                      <th style={{ padding: '0.25rem' }}>Status</th>
                      <th style={{ padding: '0.25rem' }}>Severity</th>
                      <th style={{ padding: '0.25rem' }}>Details</th>
                      <th style={{ padding: '0.25rem' }}>Hint</th>
                    </tr>
                  </thead>
                  <tbody>
                    {doctorReport.checks.map((check, i) => (
                      <tr
                        key={i}
                        style={{
                          background:
                            !check.ok && check.severity === 'fatal'
                              ? '#fee'
                              : !check.ok && check.severity === 'warn'
                                ? '#ffc'
                                : 'transparent',
                        }}
                      >
                        <td style={{ padding: '0.25rem', fontFamily: 'monospace' }}>
                          {check.name}
                        </td>
                        <td style={{ padding: '0.25rem' }}>
                          <span style={{ color: check.ok ? '#080' : '#c00' }}>
                            {check.ok ? 'OK' : 'FAIL'}
                          </span>
                        </td>
                        <td
                          style={{
                            padding: '0.25rem',
                            color:
                              check.severity === 'fatal'
                                ? '#c00'
                                : check.severity === 'warn'
                                  ? '#c80'
                                  : '#666',
                          }}
                        >
                          {check.severity}
                        </td>
                        <td style={{ padding: '0.25rem', fontSize: '0.9em' }}>
                          {check.details}
                        </td>
                        <td style={{ padding: '0.25rem', fontSize: '0.9em', color: '#666' }}>
                          {check.hint}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}

          <button
            onClick={loadDoctor}
            disabled={doctorLoading}
            style={{ marginTop: '0.5rem' }}
          >
            {doctorLoading ? 'Running...' : 'Run Doctor'}
          </button>
        </div>

        {/* Smoke Test */}
        <div
          style={{
            background: '#f5f5f5',
            padding: '1rem',
            borderRadius: '4px',
            marginBottom: '1rem',
          }}
        >
          <h3 style={{ marginTop: 0 }}>Smoke Test</h3>
          <p style={{ color: '#666', marginBottom: '0.5rem' }}>
            Boot an ephemeral microVM to verify Firecracker is working correctly.
          </p>

          {smokeLoading && <p>Running smoke test (this may take 20+ seconds)...</p>}
          {smokeError && <p style={{ color: 'red' }}>Error: {smokeError}</p>}

          {smokeResult && (
            <div
              style={{
                background: smokeResult.ok ? '#efe' : '#fee',
                border: `1px solid ${smokeResult.ok ? '#0c0' : '#c00'}`,
                padding: '0.5rem',
                borderRadius: '4px',
                marginBottom: '0.5rem',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                <span
                  style={{
                    color: smokeResult.ok ? '#080' : '#c00',
                    fontWeight: 'bold',
                  }}
                >
                  {smokeResult.ok ? 'PASSED' : 'FAILED'}
                </span>
                {smokeResult.runtime_enabled && (
                  <span style={{ color: '#080' }}>Firecracker enabled!</span>
                )}
                {smokeResult.error && (
                  <span style={{ color: '#c00' }}>{smokeResult.error}</span>
                )}
              </div>

              {smokeResult.timings && (
                <div style={{ marginTop: '0.5rem', fontFamily: 'monospace', fontSize: '0.9em' }}>
                  Boot: {smokeResult.timings.boot_ms}ms |
                  Ready: {smokeResult.timings.ready_ms}ms |
                  Teardown: {smokeResult.timings.teardown_ms}ms |
                  Total: {smokeResult.timings.total_ms}ms
                </div>
              )}

              {smokeResult.notes.length > 0 && (
                <div style={{ marginTop: '0.5rem', fontSize: '0.85em' }}>
                  <strong>Notes:</strong>
                  <ul style={{ margin: '0.25rem 0', paddingLeft: '1.5rem' }}>
                    {smokeResult.notes.map((note, i) => (
                      <li key={i}>{note}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}

          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <button
              onClick={() => handleRunSmoke(false)}
              disabled={smokeLoading}
              style={{ padding: '0.5rem 1rem' }}
            >
              {smokeLoading ? 'Running...' : 'Run Smoke'}
            </button>
            <button
              onClick={() => handleRunSmoke(true)}
              disabled={smokeLoading}
              style={{
                padding: '0.5rem 1rem',
                background: '#080',
                color: 'white',
              }}
            >
              Run Smoke + Enable Firecracker
            </button>
          </div>
        </div>

        {/* Disable Firecracker */}
        {runtimeStatus?.effective_runtime === 'firecracker' && (
          <div
            style={{
              background: '#fff3cd',
              border: '1px solid #ffc107',
              padding: '1rem',
              borderRadius: '4px',
            }}
          >
            <strong>Firecracker is currently enabled for new labs.</strong>
            <p style={{ margin: '0.5rem 0', color: '#666' }}>
              Note: Firecracker runtime is not yet fully implemented. New lab creation will
              return 503 until the runtime is complete.
            </p>
            <button
              onClick={handleDisableFirecracker}
              disabled={runtimeLoading}
              style={{
                background: '#c00',
                color: 'white',
                padding: '0.5rem 1rem',
              }}
            >
              {runtimeLoading ? 'Disabling...' : 'Disable Firecracker'}
            </button>
          </div>
        )}

        {/* Firecracker Runtime Status (Live) */}
        <div
          style={{
            background: '#f5f5f5',
            padding: '1rem',
            borderRadius: '4px',
            marginTop: '1rem',
          }}
        >
          <h3 style={{ marginTop: 0 }}>Firecracker Runtime Status (Live)</h3>
          <p style={{ color: '#666', marginBottom: '0.5rem' }}>
            Real-time status of running Firecracker processes and lab VMs.
            Detects drift between DB state and actual running processes.
          </p>

          {fcStatusLoading && <p>Loading Firecracker status...</p>}
          {fcStatusError && <p style={{ color: 'red' }}>Error: {fcStatusError}</p>}

          {fcStatus && (
            <div>
              {/* Summary */}
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '1rem',
                  marginBottom: '0.5rem',
                  padding: '0.5rem',
                  background: fcStatus.drift.db_running_no_pid.length === 0 && fcStatus.drift.orphan_pids.length === 0
                    ? '#d4edda'
                    : '#fff3cd',
                  borderRadius: '4px',
                }}
              >
                <span
                  style={{
                    color: fcStatus.drift.db_running_no_pid.length === 0 && fcStatus.drift.orphan_pids.length === 0
                      ? '#155724'
                      : '#856404',
                    fontWeight: 'bold',
                  }}
                >
                  {fcStatus.drift.db_running_no_pid.length === 0 && fcStatus.drift.orphan_pids.length === 0
                    ? 'OK'
                    : 'DRIFT DETECTED'}
                </span>
                <span>
                  <strong>Processes:</strong> {fcStatus.firecracker_process_count}
                </span>
                <span>
                  <strong>Labs:</strong> {fcStatus.running_microvm_labs.length}
                </span>
                {fcStatus.drift.db_running_no_pid.length > 0 && (
                  <span style={{ color: '#c00' }}>
                    Missing PIDs: {fcStatus.drift.db_running_no_pid.length}
                  </span>
                )}
                {fcStatus.drift.orphan_pids.length > 0 && (
                  <span style={{ color: '#c80' }}>
                    Orphan PIDs: {fcStatus.drift.orphan_pids.length}
                  </span>
                )}
              </div>

              <p style={{ fontFamily: 'monospace', fontSize: '0.9em', margin: '0.5rem 0' }}>
                {fcStatus.summary}
              </p>

              {/* Labs Table */}
              {fcStatus.running_microvm_labs.length > 0 && (
                <div style={{ marginTop: '0.5rem' }}>
                  <button
                    onClick={() => setShowFcLabs(!showFcLabs)}
                    style={{ fontSize: '0.9em', padding: '0.25rem 0.5rem' }}
                  >
                    {showFcLabs ? 'Hide' : 'Show'} Labs ({fcStatus.running_microvm_labs.length})
                  </button>

                  {showFcLabs && (
                    <table
                      style={{
                        marginTop: '0.5rem',
                        fontSize: '0.85em',
                        width: '100%',
                        borderCollapse: 'collapse',
                      }}
                    >
                      <thead>
                        <tr style={{ textAlign: 'left', borderBottom: '1px solid #ddd' }}>
                          <th style={{ padding: '0.25rem' }}>Lab ID</th>
                          <th style={{ padding: '0.25rem' }}>VM ID</th>
                          <th style={{ padding: '0.25rem' }}>PID</th>
                          <th style={{ padding: '0.25rem' }}>Socket</th>
                          <th style={{ padding: '0.25rem' }}>State Dir</th>
                          <th style={{ padding: '0.25rem' }}>Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        {fcStatus.running_microvm_labs.map((lab) => (
                          <tr
                            key={lab.lab_id}
                            style={{
                              background:
                                lab.status === 'ok'
                                  ? 'transparent'
                                  : lab.status === 'missing_pid'
                                    ? '#fee'
                                    : '#ffc',
                            }}
                          >
                            <td style={{ padding: '0.25rem', fontFamily: 'monospace' }}>
                              {lab.lab_id.substring(0, 8)}...
                            </td>
                            <td style={{ padding: '0.25rem', fontFamily: 'monospace' }}>
                              {lab.vm_id ?? '-'}
                            </td>
                            <td style={{ padding: '0.25rem' }}>
                              {lab.firecracker_pid ?? '-'}
                            </td>
                            <td style={{ padding: '0.25rem' }}>
                              <span style={{ color: lab.api_sock_exists ? '#080' : '#c00' }}>
                                {lab.api_sock_exists ? 'present' : 'missing'}
                              </span>
                            </td>
                            <td style={{ padding: '0.25rem' }}>
                              <span style={{ color: lab.state_dir_exists ? '#080' : '#c00' }}>
                                {lab.state_dir_exists ? 'present' : 'missing'}
                              </span>
                            </td>
                            <td style={{ padding: '0.25rem' }}>
                              <span
                                style={{
                                  color:
                                    lab.status === 'ok'
                                      ? '#080'
                                      : lab.status === 'missing_pid'
                                        ? '#c00'
                                        : '#c80',
                                  fontWeight: 'bold',
                                }}
                              >
                                {lab.status.toUpperCase()}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              )}

              {/* Drift Details */}
              {(fcStatus.drift.db_running_no_pid.length > 0 || fcStatus.drift.orphan_pids.length > 0) && (
                <div
                  style={{
                    marginTop: '0.5rem',
                    padding: '0.5rem',
                    background: '#fff3cd',
                    borderRadius: '4px',
                    fontSize: '0.85em',
                  }}
                >
                  <strong>Drift Details:</strong>
                  {fcStatus.drift.db_running_no_pid.length > 0 && (
                    <div style={{ marginTop: '0.25rem' }}>
                      <span style={{ color: '#c00' }}>DB running but no PID:</span>{' '}
                      {fcStatus.drift.db_running_no_pid.map((id) => id.substring(0, 8)).join(', ')}
                    </div>
                  )}
                  {fcStatus.drift.orphan_pids.length > 0 && (
                    <div style={{ marginTop: '0.25rem' }}>
                      <span style={{ color: '#c80' }}>Orphan PIDs:</span>{' '}
                      {fcStatus.drift.orphan_pids.join(', ')}
                    </div>
                  )}
                </div>
              )}

              <div style={{ marginTop: '0.5rem', fontSize: '0.8em', color: '#666' }}>
                Generated: {new Date(fcStatus.generated_at).toLocaleString()}
              </div>
            </div>
          )}

          <button
            onClick={loadFirecrackerStatus}
            disabled={fcStatusLoading}
            style={{ marginTop: '0.5rem' }}
          >
            {fcStatusLoading ? 'Loading...' : 'Refresh Firecracker Status'}
          </button>
        </div>
      </section>
    </div>
  )
}
