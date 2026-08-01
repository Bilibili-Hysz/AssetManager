import { Navigate, Outlet } from 'react-router-dom';
import { useAuth } from '../../hooks/useAuth';
import type { Capabilities } from '../../types/api';

export default function ProtectedRoute({ capability }: { capability: keyof Capabilities }) {
  const { isLoading, isAuthenticated, capabilities, serverInfo } = useAuth();

  if (isLoading) return null;
  const openGuest = serverInfo?.auth_enabled === false && capabilities[capability];
  if (!isAuthenticated && !openGuest) return <Navigate to="/login" replace />;
  if (!capabilities[capability]) return <Navigate to="/" replace />;
  return <Outlet />;
}
