import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { deleteLab, downloadLabEvidence, fetchLab, getLabConnectUrl } from '../api/client'
import type { EvidenceState, Lab } from '../api/client'
import { useAuth } from '../hooks/useAuth'

// Status helpers
const isActiveStatus = (status: string) =>
  status === 'provisioning' || status === 'ending'

const isTerminalStatus = (status: string) =>
  status === 'finished' || status === 'failed'

const isRuntimeAvailable = (status: string) =>
  status === 'ready'

const isProvisioning = (status: string) =>
  status === 'provisioning' || status === 'requested'

// Evidence state badge styling
const getEvidenceBadgeStyle = (state: EvidenceState | null | undefined): React.CSSProperties => {
  const baseStyle: React.CSSProperties = {
    display: 'inline-block',
    padding: '0.25rem 0.5rem',
    borderRadius: '4px',
    fontSize: '0.875rem',
    fontWeight: 500,
    marginLeft: '0.5rem',
  }
  switch (state) {
    case 'ready':
      return { ...baseStyle, backgroundColor: '#d4edda', color: '#155724' }
    case 'partial':
      return { ...baseStyle, backgroundColor: '#fff3cd', color: '#856404' }
    case 'collecting':
      return { ...baseStyle, backgroundColor: '#cce5ff', color: '#004085' }
    case 'unavailable':
      return { ...baseStyle, backgroundColor: '#f8d7da', color: '#721c24' }
    default:
      return { ...baseStyle, backgroundColor: '#e2e3e5', color: '#383d41' }
  }
}

const getEvidenceBadgeLabel = (
  state: EvidenceState | null | undefined,
  labStatus?: string,
): string => {
  // Special case: terminal lab stuck in collecting should show "Finalizing..."
  if (state === 'collecting' && labStatus && isTerminalStatus(labStatus)) {
    return 'Finalizing...'
  }
  switch (state) {
    case 'ready':
      return 'Evidence Ready'
    case 'partial':
      return 'Evidence Partial'
    case 'collecting':
      return 'Collecting...'
    case 'unavailable':
      return 'Evidence Unavailable'
    default:
      return 'Evidence: Unknown'
  }
}

const LabPage = () => {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { user, logout } = useAuth()
  const [lab, setLab] = useState<Lab | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isTerminating, setIsTerminating] = useState(false)
  const [isDownloading, setIsDownloading] = useState(false)
  const [isConnecting, setIsConnecting] = useState(false)

  // Refetch lab data helper
  const refetchLab = async () => {
    if (!id) return
    try {
      const data = await fetchLab(id)
      setLab(data)
    } catch (err: unknown) {
      // Check for 404 - lab was deleted
      if (err && typeof err === 'object' && 'response' in err) {
        const axiosErr = err as { response?: { status?: number } }
        if (axiosErr.response?.status === 404) {
          setError('Lab was deleted.')
          navigate('/labs')
          return
        }
      }
      console.error('Refetch error:', err)
    }
  }

  useEffect(() => {
    const load = async () => {
      if (!id) return
      try {
        const data = await fetchLab(id)
        setLab(data)
      } catch (err) {
        console.error(err)
        setError('Unable to load lab.')
      } finally {
        setIsLoading(false)
      }
    }
    load()
  }, [id])

  // Refetch on window focus/visibility change to pick up server-side state updates
  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible' && id && lab) {
        refetchLab()
      }
    }
    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange)
  }, [id, lab])

  // Poll lab status when it's in an active state
  useEffect(() => {
    if (!lab || !id) return

    if (!isActiveStatus(lab.status) || isTerminalStatus(lab.status)) {
      return
    }

    const intervalId = setInterval(async () => {
      try {
        const updated = await fetchLab(id)
        setLab(updated)
      } catch (err) {
        console.error('Polling error:', err)
      }
    }, 4000)

    return () => clearInterval(intervalId)
  }, [id, lab?.status])

  // One-time refetch for terminal labs with evidence_state still 'collecting'
  // This triggers backend reconciliation and updates the badge
  useEffect(() => {
    if (!lab || !id) return
    if (!isTerminalStatus(lab.status)) return
    if (lab.evidence_state !== 'collecting') return

    // Wait a short delay then refetch once to trigger reconciliation
    const timeoutId = setTimeout(async () => {
      try {
        const updated = await fetchLab(id)
        setLab(updated)
      } catch (err) {
        console.error('Evidence reconcile refetch error:', err)
      }
    }, 2000)

    return () => clearTimeout(timeoutId)
  }, [id, lab?.status, lab?.evidence_state])

  if (isLoading) {
    return (
      <div className="page">
        <p>Loading lab…</p>
      </div>
    )
  }

  if (error || !lab) {
    return (
      <div className="page">
        <p className="error">{error ?? 'Lab not found.'}</p>
        <Link to="/labs">Back to labs</Link>
      </div>
    )
  }

  const handleTerminate = async () => {
    if (!id) return
    setIsTerminating(true)
    setError(null)
    try {
      await deleteLab(id)
      setLab((prev) => (prev ? { ...prev, status: 'ending' } : prev))
      navigate('/labs')
    } catch (err) {
      console.error(err)
      setError('Failed to terminate lab.')
    } finally {
      setIsTerminating(false)
    }
  }

  const handleDownload = async () => {
    if (!id) return
    setIsDownloading(true)
    setError(null)
    try {
      const { blob, filename } = await downloadLabEvidence(id)
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = filename
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
    } catch (err) {
      console.error(err)
      setError('Failed to download evidence.')
    } finally {
      setIsDownloading(false)
      // Refetch lab to update evidence_state badge (server may have reconciled)
      await refetchLab()
    }
  }

  const handleConnect = async () => {
    if (!id) return
    setIsConnecting(true)
    setError(null)
    try {
      const { redirect_url } = await getLabConnectUrl(id)
      // Open Guacamole in new tab
      window.open(redirect_url, '_blank', 'noopener,noreferrer')
    } catch (err: unknown) {
      console.error(err)
      // Extract backend error message if available
      let errorMsg = 'Failed to connect to OctoBox.'
      if (err && typeof err === 'object' && 'response' in err) {
        const axiosErr = err as { response?: { data?: { detail?: string }, status?: number } }
        if (axiosErr.response?.data?.detail) {
          errorMsg = axiosErr.response.data.detail
        } else if (axiosErr.response?.status === 409) {
          errorMsg = 'Lab is not ready for connection.'
        }
      }
      setError(errorMsg)
    } finally {
      setIsConnecting(false)
    }
  }

  const getStatusDisplay = (status: string) => {
    if (status === 'provisioning') return 'Starting lab…'
    if (status === 'ending') return 'Stopping lab…'
    return status
  }

  return (
    <div className="page">
      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h1>Lab {lab.id}</h1>
        <div>
          {user && <span style={{ marginRight: '1rem' }}>{user.email}</span>}
          {user?.is_admin && (
            <Link to="/admin" style={{ marginRight: '1rem' }}>
              Admin
            </Link>
          )}
          <button onClick={logout}>Logout</button>
        </div>
      </header>
      <p>
        Status: {getStatusDisplay(lab.status)}
        {/* Evidence state badge - always shown */}
        <span style={getEvidenceBadgeStyle(lab.evidence_state)}>
          {getEvidenceBadgeLabel(lab.evidence_state, lab.status)}
        </span>
        {/* Runtime badge - show only for non-default runtime (firecracker) */}
        {lab.runtime === 'firecracker' && (
          <span
            style={{
              display: 'inline-block',
              padding: '0.25rem 0.5rem',
              borderRadius: '4px',
              fontSize: '0.875rem',
              fontWeight: 500,
              marginLeft: '0.5rem',
              backgroundColor: '#e7f1ff',
              color: '#0d6efd',
            }}
          >
            Firecracker
          </span>
        )}
      </p>
      <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
        <button
          onClick={handleTerminate}
          disabled={
            isTerminating ||
            lab.status === 'ending' ||
            lab.status === 'finished'
          }
        >
          {isTerminating ? 'Terminating…' : 'Terminate Lab'}
        </button>
        <button
          onClick={handleDownload}
          disabled={isDownloading}
          title={
            lab.evidence_state === 'unavailable'
              ? 'Evidence may be incomplete or contain only manifest'
              : lab.evidence_state === 'partial'
                ? 'Some evidence artifacts may be missing'
                : isTerminalStatus(lab.status)
                  ? 'Download final evidence bundle for this lab'
                  : 'Download current evidence snapshot (lab still running)'
          }
        >
          {isDownloading
            ? 'Downloading…'
            : isTerminalStatus(lab.status)
              ? 'Download Evidence (final)'
              : 'Download Evidence (snapshot)'}
        </button>
        {lab.evidence_state === 'unavailable' && (
          <span style={{ fontSize: '0.75rem', color: '#856404', marginLeft: '0.5rem' }}>
            ⚠ May contain only manifest
          </span>
        )}
      </div>
      {/* OctoBox connection section */}
      <div style={{ marginTop: '1rem' }}>
        {isRuntimeAvailable(lab.status) ? (
          <button onClick={handleConnect} disabled={isConnecting}>
            {isConnecting ? 'Connecting…' : 'Open OctoBox'}
          </button>
        ) : isProvisioning(lab.status) ? (
          <button disabled style={{ opacity: 0.6, cursor: 'not-allowed' }}>
            Provisioning…
          </button>
        ) : isTerminalStatus(lab.status) ? (
          <button disabled style={{ opacity: 0.6, cursor: 'not-allowed' }} title="Lab has stopped">
            Lab Stopped
          </button>
        ) : (
          <button disabled style={{ opacity: 0.6, cursor: 'not-allowed' }}>
            OctoBox Unavailable
          </button>
        )}
        {isTerminalStatus(lab.status) && (
          <span style={{ fontSize: '0.875rem', color: '#6c757d', marginLeft: '0.75rem' }}>
            Lab stopped. Evidence is still available above.
          </span>
        )}
        {isProvisioning(lab.status) && (
          <span style={{ fontSize: '0.875rem', color: '#6c757d', marginLeft: '0.75rem' }}>
            OctoBox will be available when the lab is ready.
          </span>
        )}
      </div>
      <p>
        <Link to="/labs">Back to labs</Link>
      </p>
    </div>
  )
}

export default LabPage

