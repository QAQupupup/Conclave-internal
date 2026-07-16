// 认证上下文：管理登录状态、用户信息、JWT token
import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from 'react'
import { STORAGE_KEYS } from '../constants.ts'
import { setJwtToken, clearAuthToken as clearApiToken } from '../lib/api.ts'

export interface AuthUser {
  username: string
  role: string
  display_name: string
  uid?: number
}

interface AuthContextValue {
  user: AuthUser | null
  token: string | null
  loading: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => void
  isAuthenticated: boolean
  isAdmin: boolean
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [token, setToken] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  // 初始化：从 localStorage 恢复 token，验证有效性
  useEffect(() => {
    const savedToken = localStorage.getItem(STORAGE_KEYS.authToken)
    if (!savedToken) {
      setLoading(false)
      return
    }
    // 验证 token 是否有效（请求 /auth/me）
    fetch('/auth/me', {
      headers: { 'Authorization': `Bearer ${savedToken}` },
    })
      .then(res => {
        if (res.ok) return res.json()
        throw new Error('token invalid')
      })
      .then(data => {
        setToken(savedToken)
        setJwtToken(savedToken)  // 注入到 api 模块
        setUser({
          username: data.username,
          role: data.role,
          display_name: data.display_name,
          uid: data.uid,
        })
      })
      .catch(() => {
        // token 无效，清除
        localStorage.removeItem(STORAGE_KEYS.authToken)
      })
      .finally(() => setLoading(false))
  }, [])

  const login = useCallback(async (username: string, password: string) => {
    const resp = await fetch('/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    })
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: '登录失败' }))
      throw new Error(err.detail || '登录失败')
    }
    const data = await resp.json()
    const jwtToken = data.access_token
    localStorage.setItem(STORAGE_KEYS.authToken, jwtToken)
    setJwtToken(jwtToken)  // 注入到 api 模块的请求头中
    setToken(jwtToken)
    setUser({
      username: data.user.username,
      role: data.user.role,
      display_name: data.user.display_name,
      uid: data.user.uid,
    })
  }, [])

  const logout = useCallback(() => {
    localStorage.removeItem(STORAGE_KEYS.authToken)
    clearApiToken()  // 清除 api 模块中的内存 token
    setToken(null)
    setUser(null)
  }, [])

  return (
    <AuthContext.Provider
      value={{
        user,
        token,
        loading,
        login,
        logout,
        isAuthenticated: !!user,
        isAdmin: user?.role === 'admin',
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
