import * as React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router';
import { AppProviders } from './providers';
import { AppShell } from './components/layout/app-shell';
import { ProtectedRoute, PublicOnlyRoute } from './components/auth/protected-route';
import { AdminRoute } from './components/auth/admin-route';
import { ErrorBoundary } from './components/error-boundary';
import { TooltipProvider } from '@radix-ui/react-tooltip';

const LandingPage = React.lazy(() => import('./features/landing/page'));
const LoginPage = React.lazy(() => import('./features/login/page'));
const SetupPage = React.lazy(() => import('./features/setup/page'));
const BoardPage = React.lazy(() => import('./features/board/page'));
const ExplorePage = React.lazy(() => import('./features/explore/page'));
const ExploreListPage = React.lazy(() => import('./features/explore/list-page'));
const WorkspacePage = React.lazy(() => import('./features/workspace/page'));
const GraphPage = React.lazy(() => import('./features/graph/page'));
const ReportsPage = React.lazy(() => import('./features/reports/page'));
const AgentsPage = React.lazy(() => import('./features/agents/page'));
const SettingsPage = React.lazy(() => import('./features/settings/page'));
const TeamsPage = React.lazy(() => import('./features/teams/page'));
const AdminPage = React.lazy(() => import('./features/admin/page'));
const OperationsPage = React.lazy(() => import('./features/operations/page'));
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

function App() {
  return (
    <AppProviders>
      <TooltipProvider>
        <ErrorBoundary>
          <BrowserRouter>
          <React.Suspense fallback={<LoadingFallback />}>
          <Routes>
            {/* Public routes */}
            <Route path="/login" element={<PublicOnlyRoute><LoginPage /></PublicOnlyRoute>} />
            <Route path="/setup" element={<SetupPage />} />
            <Route path="/landing" element={<LandingPage />} />

            {/* Protected routes */}
            <Route element={<ProtectedRoute><AppShell /></ProtectedRoute>}>
              <Route path="/" element={<Navigate to="/board" replace />} />
              <Route path="/board" element={<BoardPage />} />
              <Route path="/explore" element={<ExploreListPage />} />
              <Route path="/explore/:id" element={<ExplorePage />} />
              <Route path="/workspace" element={<WorkspacePage />} />
              <Route path="/workspace/*" element={<WorkspacePage />} />
              <Route path="/graph" element={<GraphPage />} />
              <Route path="/reports" element={<ReportsPage />} />
              <Route path="/agents" element={<AgentsPage />} />
              <Route path="/settings" element={<SettingsPage />} />
              <Route path="/teams" element={<TeamsPage />} />
              <Route path="/admin" element={<AdminRoute><AdminPage /></AdminRoute>} />
              <Route path="/operations" element={<OperationsPage />} />
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
