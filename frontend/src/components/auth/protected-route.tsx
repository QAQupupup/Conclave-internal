import * as React from 'react';
import { Navigate, useLocation } from 'react-router';
import { useAuthStore } from '@/stores/auth-slice';

interface ProtectedRouteProps {
  children: React.ReactNode;
}

export function ProtectedRoute({ children }: ProtectedRouteProps) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const isLoading = useAuthStore((s) => s.isLoading);
  const location = useLocation();

  React.useEffect(() => {
    if (isLoading) {
      const timer = setTimeout(() => {
        useAuthStore.setState({ isLoading: false, isAuthenticated: false });
      }, 15_000);
      return () => clearTimeout(timer);
    }
  }, [isLoading]);

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-bg-primary">
        <div className="flex flex-col items-center gap-3">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-border-default border-t-brand-500" />
          <span className="text-sm text-text-tertiary">验证登录状态...</span>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  return <>{children}</>;
}

interface PublicOnlyRouteProps {
  children: React.ReactNode;
}

export function PublicOnlyRoute({ children }: PublicOnlyRouteProps) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const isLoading = useAuthStore((s) => s.isLoading);

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-bg-primary">
        <div className="flex flex-col items-center gap-3">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-border-default border-t-brand-500" />
        </div>
      </div>
    );
  }

  if (isAuthenticated) {
    return <Navigate to="/board" replace />;
  }

  return <>{children}</>;
}
