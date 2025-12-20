import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { getLabConnectUrl } from '../api/client'

const LabConnectPage = () => {
  const { id } = useParams<{ id: string }>()
  const [error, setError] = useState<string | null>(null)
  const [isConnecting, setIsConnecting] = useState(true)

  useEffect(() => {
    const connect = async () => {
      if (!id) {
        setError('No lab ID provided')
        setIsConnecting(false)
        return
      }

      try {
        const { redirect_url } = await getLabConnectUrl(id)
        // Navigate to Guacamole with the auth token
        window.location.assign(redirect_url)
      } catch (err) {
        console.error('Failed to connect to lab:', err)
        if (err && typeof err === 'object' && 'response' in err) {
          const response = (err as { response?: { status?: number; data?: { detail?: string } } }).response
          if (response?.status === 409) {
            setError(response.data?.detail ?? 'Lab is not ready for connection')
          } else if (response?.status === 404) {
            setError('Lab not found')
          } else if (response?.status === 503) {
            setError('Guacamole service is unavailable. Please try again later.')
          } else {
            setError('Failed to connect to lab')
          }
        } else {
          setError('Failed to connect to lab')
        }
        setIsConnecting(false)
      }
    }

    connect()
  }, [id])

  if (isConnecting) {
    return (
      <div className="page">
        <h1>Connecting to OctoBox...</h1>
        <p>Please wait while we establish the connection.</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="page">
        <h1>Connection Failed</h1>
        <p className="error">{error}</p>
        <p>
          <Link to={`/labs/${id}`}>Back to lab</Link>
        </p>
      </div>
    )
  }

  return null
}

export default LabConnectPage
