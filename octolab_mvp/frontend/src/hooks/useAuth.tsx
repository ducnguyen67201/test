import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import {
  fetchCurrentUser,
  loginRequest,
  registerRequest,
  setAccessToken,
  getAccessToken,
  type UserProfile,
} from '../api/client'

interface AuthContextValue {
  user: UserProfile | null
  token: string | null
  isLoading: boolean
  login: (email: string, password: string) => Promise<void>
  register: (email: string, password: string) => Promise<void>
  logout: () => void
  refreshUser: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined)

export const AuthProvider = ({ children }: { children: ReactNode }) => {
  const [token, setToken] = useState<string | null>(() => getAccessToken() ?? null)
  const [user, setUser] = useState<UserProfile | null>(null)
  const [isLoading, setIsLoading] = useState<boolean>(!!token)

  useEffect(() => {
    setAccessToken(token)
  }, [token])

  const refreshUser = useCallback(async () => {
    const currentToken = getAccessToken()
    if (!currentToken) {
      setUser(null)
      return
    }
    try {
      const { data } = await fetchCurrentUser()
      setUser(data)
    } catch {
      setToken(null)
      setUser(null)
    }
  }, [])

  useEffect(() => {
    if (!token) {
      setIsLoading(false)
      return
    }
    setIsLoading(true)
    refreshUser()
      .catch(() => {
        /* handled in refreshUser */
      })
      .finally(() => setIsLoading(false))
  }, [token, refreshUser])

  const login = useCallback(
    async (email: string, password: string) => {
      const { data } = await loginRequest({ email, password })
      setToken(data.access_token)
      await refreshUser()
    },
    [refreshUser],
  )

  const register = useCallback(
    async (email: string, password: string) => {
      const { data } = await registerRequest({ email, password })
      setToken(data.access_token)
      setUser(data.user)
    },
    [],
  )

  const logout = useCallback(() => {
    setToken(null)
    setUser(null)
  }, [])

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      token,
      isLoading,
      login,
      register,
      logout,
      refreshUser,
    }),
    [user, token, isLoading, login, register, logout, refreshUser],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export const useAuth = () => {
  const ctx = useContext(AuthContext)
  if (!ctx) {
    throw new Error('useAuth must be used inside an AuthProvider')
  }
  return ctx
}

