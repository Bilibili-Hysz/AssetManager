// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import App from './App';

const { authState } = vi.hoisted(() => ({
  authState: {
    isLoading: false,
    isAuthenticated: false,
    capabilities: { browse: false },
    serverInfo: { auth_enabled: true },
  },
}));

vi.mock('./hooks/useAuth', () => ({
  useAuth: () => authState,
}));

vi.mock('./pages/LandingPage', () => ({ default: () => <div>LandingPage</div> }));
vi.mock('./pages/LoginPage', () => ({ default: () => <div>LoginPage</div> }));
vi.mock('./pages/BrowsePage', () => ({ default: () => <div>BrowsePage</div> }));
vi.mock('./pages/DetailPage', () => ({ default: () => <div>DetailPage</div> }));
vi.mock('./pages/ShareReceivePage', () => ({ default: () => <div>ShareReceivePage</div> }));

vi.mock('./stores/AuthContext', () => ({
  AuthProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock('./stores/RealtimeContext', () => ({
  RealtimeProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock('./components/ui/Toast', () => ({
  ToastProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock('./components/ui/DownloadProgress', () => ({
  DownloadProgressProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

function navigateTo(path: string) {
  window.history.pushState({}, '', path);
}

describe('App routing', () => {
  afterEach(() => {
    cleanup();
    navigateTo('/');
  });

  it('renders LandingPage at the root path', () => {
    navigateTo('/');
    render(<App />);
    expect(screen.getByText('LandingPage')).toBeDefined();
  });

  it('renders LoginPage at /login', () => {
    navigateTo('/login');
    render(<App />);
    expect(screen.getByText('LoginPage')).toBeDefined();
  });

  it('redirects an unauthenticated user to /login when auth is enabled', () => {
    authState.isLoading = false;
    authState.isAuthenticated = false;
    authState.serverInfo = { auth_enabled: true };
    navigateTo('/browse');
    render(<App />);
    expect(screen.getByText('LoginPage')).toBeDefined();
  });

  it('lets an unauthenticated user into a protected route when auth is disabled and the capability is granted', () => {
    authState.isLoading = false;
    authState.isAuthenticated = false;
    authState.serverInfo = { auth_enabled: false };
    authState.capabilities = { browse: true };
    navigateTo('/browse');
    render(<App />);
    expect(screen.getByText('BrowsePage')).toBeDefined();
  });

  it('renders a protected route for an authenticated user with the browse capability', () => {
    authState.isLoading = false;
    authState.isAuthenticated = true;
    authState.serverInfo = { auth_enabled: true };
    authState.capabilities = { browse: true };
    navigateTo('/browse');
    render(<App />);
    expect(screen.getByText('BrowsePage')).toBeDefined();
    navigateTo('/detail');
    render(<App />);
    expect(screen.getByText('DetailPage')).toBeDefined();
  });

  it('redirects to / when the user lacks the browse capability', () => {
    authState.isLoading = false;
    authState.isAuthenticated = true;
    authState.serverInfo = { auth_enabled: true };
    authState.capabilities = { browse: false };
    navigateTo('/browse');
    render(<App />);
    expect(screen.getByText('LandingPage')).toBeDefined();
  });

  it('renders nothing while auth is loading', () => {
    authState.isLoading = true;
    navigateTo('/browse');
    render(<App />);
    expect(screen.queryByText('LandingPage')).toBeNull();
    expect(screen.queryByText('LoginPage')).toBeNull();
    expect(screen.queryByText('BrowsePage')).toBeNull();
  });

  it('renders ShareReceivePage under /s/:shareId', () => {
    navigateTo('/s/abc123');
    render(<App />);
    expect(screen.getByText('ShareReceivePage')).toBeDefined();
  });

  it('redirects unknown paths to /', () => {
    navigateTo('/does-not-exist');
    render(<App />);
    expect(screen.getByText('LandingPage')).toBeDefined();
  });
});
