import { useAuth } from '../hooks/useAuth';
import { Link, Navigate } from 'react-router-dom';

export default function LandingPage() {
  const { serverInfo, isLoading, isAuthenticated, role } = useAuth();

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="skeleton h-8 w-48" />
      </div>
    );
  }

  // If auth is enabled and user is not authenticated, redirect to login
  if (serverInfo?.auth_enabled && !isAuthenticated && role !== 'guest') {
    return <Navigate to="/login" replace />;
  }

  return (
    <div className="flex flex-col items-center justify-center h-screen gap-6 p-8 bg-slate-950">
      <h1 className="text-4xl font-bold text-white">
        {serverInfo?.share_name ?? 'AssetManager'}
      </h1>
      <p className="text-slate-400 text-lg text-center max-w-md">
        {serverInfo?.welcome_msg ?? 'Browse and download files from your asset library.'}
      </p>
      <div className="flex gap-4 mt-4">
        <Link
          to="/browse"
          className="px-6 py-3 bg-brand-500 hover:bg-brand-600 text-white rounded-lg font-medium transition-colors"
        >
          Enter Library
        </Link>
      </div>
    </div>
  );
}