// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import App from './App';

const { authState } = vi.hoisted(() => ({
  authState: {
    isLoading: false,
    isAuthenticated: false,
    capabilities: { browse: false, manage_users: false } as Record<string, boolean>,
    serverInfo: { auth_enabled: true, feature_flags: {} },
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
vi.mock('./pages/AdminPage', () => ({ default: () => <div>AdminPage</div> }));
vi.mock('./stores/AuthContext', () => ({
  AuthProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useAuthContext: () => ({
    isLoading: false,
    serverInfo: { feature_flags: {} },
  }),
}));
vi.mock('./stores/RealtimeContext', () => ({
  RealtimeProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock('./components/ui/Toast', () => ({
  ToastProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  // ApiDegradationToasts mounts inside the provider and consumes the toast API.
  useToast: () => ({ showToast: vi.fn() }),
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
    authState.serverInfo = { auth_enabled: true, feature_flags: {} };
    navigateTo('/browse');
    render(<App />);
    expect(screen.getByText('LoginPage')).toBeDefined();
  });

  it('lets an unauthenticated user into a protected route when auth is disabled and the capability is granted', async () => {
    authState.isLoading = false;
    authState.isAuthenticated = false;
    authState.serverInfo = { auth_enabled: false, feature_flags: {} };
    authState.capabilities = { browse: true };
    navigateTo('/browse');
    render(<App />);
    expect(await screen.findByText('BrowsePage')).toBeDefined();
  });

  it('renders a protected route for an authenticated user with the browse capability', async () => {
    authState.isLoading = false;
    authState.isAuthenticated = true;
    authState.serverInfo = { auth_enabled: true, feature_flags: {} };
    authState.capabilities = { browse: true };
    navigateTo('/browse');
    render(<App />);
    expect(await screen.findByText('BrowsePage')).toBeDefined();
    navigateTo('/detail');
    render(<App />);
    expect(await screen.findByText('DetailPage')).toBeDefined();
  });

  it('redirects to / when the user lacks the browse capability', () => {
    authState.isLoading = false;
    authState.isAuthenticated = true;
    authState.serverInfo = { auth_enabled: true, feature_flags: {} };
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

  it('renders ShareReceivePage under /s/:shareId', async () => {
    navigateTo('/s/abc123');
    render(<App />);
    expect(await screen.findByText('ShareReceivePage')).toBeDefined();
  });

  it('renders AdminPage at /admin for an admin with manage_users capability', async () => {
    authState.isLoading = false;
    authState.isAuthenticated = true;
    authState.capabilities = { browse: true, manage_users: true };
    navigateTo('/admin');
    render(<App />);
    expect(await screen.findByText('AdminPage')).toBeDefined();
  });

  it('redirects away from /admin without manage_users capability', async () => {
    authState.isLoading = false;
    authState.isAuthenticated = true;
    authState.capabilities = { browse: true, manage_users: false };
    navigateTo('/admin');
    render(<App />);
    // ProtectedRoute redirects to '/' (LandingPage)
    expect(await screen.findByText('LandingPage')).toBeDefined();
  });

  it('renders NotFoundPage for unknown paths', () => {
    navigateTo('/does-not-exist');
    render(<App />);
    expect(screen.getByText('Not found')).toBeDefined();
  });

  it('opens and closes the shortcut cheat sheet with the ? key', () => {
    render(<App />);
    expect(screen.queryByRole('dialog', { name: 'Keyboard shortcuts' })).toBeNull();
    fireEvent.keyDown(document, { key: '?' });
    expect(screen.getByRole('dialog', { name: 'Keyboard shortcuts' })).toBeDefined();
    // Pressing ? again while the overlay is open closes it.
    fireEvent.keyDown(document, { key: '?' });
    expect(screen.queryByRole('dialog', { name: 'Keyboard shortcuts' })).toBeNull();
  });

  it('ignores the ? key while an editable field has focus', () => {
    render(<App />);
    const input = document.createElement('input');
    document.body.appendChild(input);
    input.focus();
    fireEvent.keyDown(input, { key: '?' });
    expect(screen.queryByRole('dialog', { name: 'Keyboard shortcuts' })).toBeNull();
    input.remove();
  });
});
