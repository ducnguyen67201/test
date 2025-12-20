import type { ReactNode } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import './App.css'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import RecipesPage from './pages/RecipesPage'
import LabPage from './pages/LabPage'
import LabConnectPage from './pages/LabConnectPage'
import AdminPage from './pages/AdminPage'
import { useAuth } from './hooks/useAuth'

const RequireAuth = ({ children }: { children: ReactNode }) => {
  const { token, isLoading } = useAuth()

  if (isLoading) {
    return (
      <div className="page">
        <p>Checking session…</p>
      </div>
    )
  }

  if (!token) {
    return <Navigate to="/login" replace />
  }
  return <>{children}</>
}

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route
          path="/labs"
          element={
            <RequireAuth>
              <RecipesPage />
            </RequireAuth>
          }
        />
        <Route
          path="/labs/:id"
          element={
            <RequireAuth>
              <LabPage />
            </RequireAuth>
          }
        />
        <Route
          path="/labs/:id/connect"
          element={
            <RequireAuth>
              <LabConnectPage />
            </RequireAuth>
          }
        />
        <Route
          path="/admin"
          element={
            <RequireAuth>
              <AdminPage />
            </RequireAuth>
          }
        />
        <Route path="*" element={<Navigate to="/labs" replace />} />
      </Routes>
    </BrowserRouter>
  )
}

export default App
