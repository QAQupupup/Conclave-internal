import * as React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router';
import { AppProviders } from './providers';
import { AppShell } from './components/layout/app-shell';
import { ProtectedRoute, PublicOnlyRoute } from './components/auth/protected-route';
import { AdminRoute } from './components/auth/admin-route';
import { ErrorBoundary } from './components/error-boundary';
import { TooltipProvider } from '@radix-ui/react-tooltip';
import { useAuthStore } from './stores/auth-slice';

const LoginPage = React.lazy(() => import('./features/login/page'));
const SetupPage = React.lazy(() => import('./features/setup/page'));
const BoardPage = React.lazy(() => import('./features/board/page'));
const BoardNewPage = React.lazy(() => import('./features/board/new-page'));
const ProjectsPage = React.lazy(() => import('./features/projects/page'));
const ProjectDetailPage = React.lazy(() => import('./features/projects/detail-page'));
const MeetingCanvasPage = React.lazy(() => import('./features/meeting-canvas/page'));
const ExplorePage = React.lazy(() => import('./features/explore/page'));
const WorkspacePage = React.lazy(() => import('./features/workspace/page'));
const GraphPage = React.lazy(() => import('./features/graph/page'));
const ReportsPage = React.lazy(() => import('./features/reports/page'));
const AgentsPage = React.lazy(() => import('./features/agents/page'));
const ModelsPage = React.lazy(() => import('./features/models/page'));
const SettingsPage = React.lazy(() => import('./features/settings/page'));
const TeamsPage = React.lazy(() => import('./features/teams/page'));
const AdminPage = React.lazy(() => import('./features/admin/page'));
const OperationsPage = React.lazy(() => import('./features/operations/page'));
const MonitoringPage = React.lazy(() => import('./features/monitoring/page'));
const NotFoundPage = React.lazy(() => import('./features/not-found/page'));

function LoadingFallback() {
  return (
    <div className="flex h-screen items-center justify-center bg-bg-primary text-text-tertiary">
      <div className="flex flex-col items-center gap-3">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-border-default border-t-brand-500" />
        <span className="text-sm">加载中...</span>
      </div>
    </div>
  );
}

/**
 * AuthInit - waits for zustand persist to finish hydrating, then validates auth.
 * This is the SOLE entry point for auth initialization on page load.
 *
 * Flow:
 * 1. Wait for zustand persist hydration to complete
 * 2. If token exists in localStorage → fetchUser() to validate it
 * 3. If fetchUser fails (token expired) → try silentRefresh() as fallback
 * 4. If no token → try silentRefresh() (uses HttpOnly refresh_token cookie)
 * 5. If all fails → mark not authenticated, stop loading
 */
function AuthInit() {
  const [hydrated, setHydrated] = React.useState(false);
  const initRef = React.useRef(false);

  React.useEffect(() => {
    const alreadyHydrated = useAuthStore.persist.hasHydrated();
    if (alreadyHydrated) {
      setHydrated(true);
      return;
    }
    const unsub = useAuthStore.persist.onFinishHydration(() => {
      setHydrated(true);
    });

    // Fallback: if persist hydration doesn't complete within the configured
    // timeout, force proceed. This handles edge cases where zustand persist
    // gets stuck (browser blocks localStorage, storage quota exceeded, etc.).
    // The timeout is configurable via VITE_AUTH_HYDRATION_TIMEOUT_MS (default 3000ms).
    // NOTE: This is a specialized fallback for zustand persist hydration only.
    // Do NOT copy this pattern to other async init scenarios — use Suspense/loading instead.
    const HYDRATION_TIMEOUT = Number(import.meta.env.VITE_AUTH_HYDRATION_TIMEOUT_MS) || 3000;
    const PERSIST_VERSION = 1; // MUST match the `version` in auth-slice.ts persist config
    const timeout = setTimeout(() => {
      if (!useAuthStore.persist.hasHydrated()) {
        let manualLoadSucceeded = false;
        try {
          const raw = localStorage.getItem('conclave:auth');
          if (raw) {
            const parsed = JSON.parse(raw);
            // Version check: discard stale data if store schema changed,
            // preventing old malformed data from being injected into the store.
            if (parsed && parsed.version === PERSIST_VERSION) {
              const token = parsed?.state?.token;
              if (typeof token === 'string' && token.length > 0) {
                useAuthStore.setState({ token });
                manualLoadSucceeded = true;
              }
            }
          }
        } catch {
          // localStorage read/parse errors are non-fatal
        }
        if (!manualLoadSucceeded) {
          // Hydration failed and no valid token could be recovered — clear any
          // stale auth state so the user sees a clean login redirect instead of
          // a confusing half-authenticated state.
          useAuthStore.setState({ token: null, user: null, isAuthenticated: false });
          // Signal to the login page that this redirect was caused by a
          // session recovery failure (not an explicit logout), so it can show
          // a user-visible explanation instead of silently appearing.
          try { sessionStorage.setItem('conclave:auth-hydration-failed', '1'); } catch { /* ignore */ }
        }
        setHydrated(true);
      }
    }, HYDRATION_TIMEOUT);

    return () => {
      unsub();
      clearTimeout(timeout);
    };
  }, []);

  React.useEffect(() => {
    if (!hydrated || initRef.current) return;
    initRef.current = true;

    const { token, fetchUser, silentRefresh, setLoading } = useAuthStore.getState();

    const initAuth = async () => {
      if (token) {
        const user = await fetchUser();
        if (user) return;

        const refreshed = await silentRefresh();
        if (refreshed) return;
      } else {
        const refreshed = await silentRefresh();
        if (refreshed) return;
      }

      setLoading(false);
    };

    initAuth();
  }, [hydrated]);

  return null;
}

function App() {
  return (
    <AppProviders>
      <TooltipProvider>
        <ErrorBoundary>
          <BrowserRouter>
            <AuthInit />
            <React.Suspense fallback={<LoadingFallback />}>
            <Routes>
              {/* Public routes */}
              <Route path="/login" element={<PublicOnlyRoute><LoginPage /></PublicOnlyRoute>} />
              <Route path="/setup" element={<SetupPage />} />

              {/* Protected routes */}
              <Route element={<ProtectedRoute><AppShell /></ProtectedRoute>}>
                <Route path="/" element={<Navigate to="/board" replace />} />
                <Route path="/board" element={<BoardPage />} />
                <Route path="/board/new" element={<BoardNewPage />} />
                <Route path="/projects" element={<ProjectsPage />} />
                <Route path="/projects/:id" element={<ProjectDetailPage />} />
                {/* 会议视图：/meeting 为正式路由；/explore 旧链接重定向不失效 */}
                <Route path="/meeting/:id" element={<ExplorePage />} />
                {/* 路由画布：整页档画布（可开新标签页/分享），见 features/meeting-canvas */}
                <Route path="/meeting/:id/canvas/:kind" element={<MeetingCanvasPage />} />
                <Route path="/explore" element={<Navigate to="/board" replace />} />
                {/* 旧 /explore/:id 链接兼容：复用同一会议视图组件 */}
                <Route path="/explore/:id" element={<ExplorePage />} />
                <Route path="/workspace" element={<WorkspacePage />} />
                <Route path="/workspace/*" element={<WorkspacePage />} />
                <Route path="/graph" element={<GraphPage />} />
                <Route path="/reports" element={<ReportsPage />} />
                <Route path="/agents" element={<AgentsPage />} />
                <Route path="/models" element={<ModelsPage />} />
                <Route path="/settings" element={<SettingsPage />} />
                <Route path="/teams" element={<TeamsPage />} />
                <Route path="/admin" element={<AdminRoute><AdminPage /></AdminRoute>} />
                <Route path="/operations" element={<OperationsPage />} />
                <Route path="/monitoring" element={<MonitoringPage />} />
              </Route>

              <Route path="*" element={<NotFoundPage />} />
            </Routes>
            </React.Suspense>
          </BrowserRouter>
        </ErrorBoundary>
      </TooltipProvider>
    </AppProviders>
  );
}

export default App;
