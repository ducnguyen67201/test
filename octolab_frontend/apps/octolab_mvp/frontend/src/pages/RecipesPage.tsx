import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import axios from 'axios'
import {
  createLab,
  deleteLab,
  downloadLabEvidence,
  fetchLabs,
  fetchRecipes,
} from '../api/client'
import type { Lab, Recipe } from '../api/client'
import { useAuth } from '../hooks/useAuth'

const RecipesPage = () => {
  const navigate = useNavigate()
  const { token, user, logout } = useAuth()
  const [recipes, setRecipes] = useState<Recipe[]>([])
  const [labs, setLabs] = useState<Lab[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [isStarting, setIsStarting] = useState<string | null>(null)
  const [isTerminating, setIsTerminating] = useState<string | null>(null)
  const [isDownloading, setIsDownloading] = useState<string | null>(null)
  const [statusFilter, setStatusFilter] = useState<string>('active')

  useEffect(() => {
    if (!token) {
      navigate('/login', { replace: true })
      return
    }
    const load = async () => {
      setIsLoading(true)
      setError(null)
      try {
        const [recipesData, labsData] = await Promise.all([
          fetchRecipes(),
          fetchLabs(),
        ])
        setRecipes(recipesData)
        setLabs(labsData)
      } catch (err) {
        console.error(err)
        setError('Unable to load data from server.')
      } finally {
        setIsLoading(false)
      }
    }
    load()
  }, [token, navigate])

  const refreshLabs = async () => {
    try {
      const labsData = await fetchLabs()
      setLabs(labsData)
    } catch (err) {
      console.error(err)
      setError('Unable to refresh labs list.')
    }
  }

  const handleStartLab = async (recipeId: string) => {
    setIsStarting(recipeId)
    setError(null)
    try {
      const lab = await createLab(recipeId)
      // Lab provisioning happens automatically in the background after POST /labs
      navigate(`/labs/${lab.id}`)
    } catch (err) {
      console.error(err)
      if (axios.isAxiosError(err) && err.response?.status === 409) {
        setError('You already have an active lab. Please open or terminate it before starting another.')
      } else {
        setError('Failed to start lab. Please try again.')
      }
    } finally {
      setIsStarting(null)
    }
  }

  const handleTerminateLab = async (labId: string) => {
    setIsTerminating(labId)
    setError(null)
    try {
      await deleteLab(labId)
      await refreshLabs()
      // Clear any 409 error after successful termination
      setError(null)
    } catch (err) {
      console.error(err)
      setError('Failed to terminate lab. Please try again.')
    } finally {
      setIsTerminating(null)
    }
  }

  const handleDownloadEvidence = async (labId: string) => {
    setIsDownloading(labId)
    setError(null)
    try {
      const { blob, filename } = await downloadLabEvidence(labId)
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
      setIsDownloading(null)
    }
  }

  if (isLoading) {
    return (
      <div className="page">
        <p>Loading recipes…</p>
      </div>
    )
  }

  const filteredLabs = labs.filter((lab) => {
    if (statusFilter === 'active') {
      return ['provisioning', 'ready', 'failed'].includes(lab.status.toLowerCase())
    }
    if (statusFilter === 'all') {
      return true
    }
    return lab.status.toLowerCase() === statusFilter.toLowerCase()
  })

  return (
    <div className="page">
      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h1>Recipes</h1>
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
      {error && <p className="error">{error}</p>}
      <div className="card">
        <h2>Your Labs</h2>
        <div style={{ marginBottom: '1rem' }}>
          <label htmlFor="status-filter" style={{ marginRight: '0.5rem' }}>
            Filter:
          </label>
          <select
            id="status-filter"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            style={{ padding: '0.25rem 0.5rem' }}
          >
            <option value="active">Active</option>
            <option value="all">All</option>
            <option value="requested">Requested</option>
            <option value="provisioning">Provisioning</option>
            <option value="ready">Ready</option>
            <option value="ending">Ending</option>
            <option value="finished">Finished</option>
            <option value="failed">Failed</option>
          </select>
        </div>
        {filteredLabs.length === 0 ? (
          <p>No labs yet. Start one below.</p>
        ) : (
          <div className="table-wrapper">
            <table>
              <thead>
                <tr>
                  <th>Lab ID</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredLabs.map((lab) => (
                  <tr key={lab.id}>
                    <td>
                      <Link to={`/labs/${lab.id}`}>{lab.id}</Link>
                    </td>
                    <td>{lab.status}</td>
                    <td>
                      <button
                        onClick={() => navigate(`/labs/${lab.id}`)}
                        style={{ marginRight: '0.5rem' }}
                      >
                        View
                      </button>
                      <button
                        onClick={() => handleTerminateLab(lab.id)}
                        disabled={
                          isTerminating === lab.id ||
                          lab.status === 'ending' ||
                          lab.status === 'finished'
                        }
                        style={{ marginRight: '0.5rem' }}
                      >
                        {isTerminating === lab.id
                          ? 'Terminating…'
                          : 'Terminate'}
                      </button>
                      <button
                        onClick={() => handleDownloadEvidence(lab.id)}
                        disabled={
                          isDownloading === lab.id ||
                          !['ready', 'failed', 'finished'].includes(
                            lab.status.toLowerCase(),
                          )
                        }
                        title={
                          ['ready', 'failed', 'finished'].includes(
                            lab.status.toLowerCase(),
                          )
                            ? 'Download network evidence for this lab'
                            : 'Evidence is only available for ready, failed, or finished labs'
                        }
                      >
                        {isDownloading === lab.id
                          ? 'Downloading…'
                          : 'Evidence'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      <div className="card">
        {recipes.length === 0 ? (
          <p>No recipes available.</p>
        ) : (
          <div className="table-wrapper">
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Software</th>
                  <th>Version</th>
                  <th>Exploit Family</th>
                  <th>Description</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {recipes.map((recipe) => (
                  <tr key={recipe.id}>
                    <td>{recipe.name}</td>
                    <td>{recipe.software ?? '—'}</td>
                    <td>{recipe.version_constraint ?? '—'}</td>
                    <td>{recipe.exploit_family ?? '—'}</td>
                    <td>{recipe.description ?? '—'}</td>
                    <td>
                      <button
                        onClick={() => handleStartLab(recipe.id)}
                        disabled={isStarting === recipe.id}
                      >
                        {isStarting === recipe.id ? 'Starting…' : 'Start Lab'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

export default RecipesPage

