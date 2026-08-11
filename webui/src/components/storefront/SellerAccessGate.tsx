import { Navigate, Outlet } from 'react-router-dom';
import { useSellerAuth } from '../../stores/SellerAuthContext';
import SellerLoginPage from '../../pages/SellerLoginPage';

export function SellerAccessGate() {
  const { enabled, authenticated, loading } = useSellerAuth();
  if (loading) return null;
  if (!enabled) return <Navigate to="/storefront" replace />;
  if (!authenticated) return <SellerLoginPage />;
  return <Outlet />;
}
