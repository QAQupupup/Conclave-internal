/* Conclave 认证存储 — ported from app.html (localStorage JWT) */

export const TOKEN_KEY = 'conclave_token';
export const USER_KEY = 'conclave_user';

export interface ConclaveUser {
  id?: string;
  username?: string;
  display_name?: string;
  role?: string;
  [k: string]: unknown;
}

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) || '';
}
export function setToken(t: string): void {
  localStorage.setItem(TOKEN_KEY, t);
}
export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}
export function getStoredUser(): ConclaveUser | null {
  try {
    return JSON.parse(localStorage.getItem(USER_KEY) || 'null');
  } catch {
    return null;
  }
}
export function setStoredUser(u: ConclaveUser | null): void {
  if (u) localStorage.setItem(USER_KEY, JSON.stringify(u));
  else localStorage.removeItem(USER_KEY);
}

/** 轻量认证状态订阅（供 React 组件响应登录/登出变化） */
type Listener = (user: ConclaveUser | null) => void;
let currentUser: ConclaveUser | null = getStoredUser();
const listeners = new Set<Listener>();

export function getAuthUser(): ConclaveUser | null {
  return currentUser;
}

export function subscribeAuth(fn: Listener): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/** 登录成功后写入 token+user 并通知订阅者 */
export function commitLogin(token: string, user: ConclaveUser): void {
  setToken(token);
  setStoredUser(user);
  currentUser = user;
  listeners.forEach((l) => l(currentUser));
}

/** 登出：清除凭据并通知订阅者 */
export function commitLogout(): void {
  clearToken();
  currentUser = null;
  listeners.forEach((l) => l(currentUser));
}
