// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ProtectedRoute from './ProtectedRoute';
import type { Capabilities, SessionPrincipal } from '../../types/api';

const authState: {
  isLoading: boolean;
  isAuthenticated: boolean;
  capabilities: Capabilities;
  principal: SessionPrincipal;
  serverInfo: { auth_enabled: boolean } | null;
} = {
  isLoading: false,
  isAuthenticated: false,
  serverInfo: { auth_enabled: true },
  capabilities: {
    browse: false, preview: false, download: false, upload: false, manage_links: false,
    manage_users: false, settings: false, realtime: false,
  } satisfies Capabilities,
  principal: {
    kind: 'guest' as const,
    authenticated: false,
    role: 'guest' as const,
    display_name: 'Guest',
    capabilities: { browse: false, preview: false, download: false, upload: false, manage_links: false, manage_users: false, settings: false, realtime: false },
  },
};

vi.mock('../../hooks/useAuth', () => ({
  useAuth: () => authState,
}));

function renderRoute() {
  return render(
    <MemoryRouter initialEntries={['/browse']}>
      <Routes>
        <Route path="/" element={<p>Forbidden screen</p>} />
        <Route path="/login" element={<p>Login screen</p>} />
        <Route path="/forbidden" element={<p>Forbidden screen</p>} />
        <Route element={<ProtectedRoute capability="browse" />}>
          <Route path="/browse" element={<p>Browse screen</p>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe('ProtectedRoute', () => {
  afterEach(cleanup);

  beforeEach(() => {
    authState.isAuthenticated = false;
    authState.serverInfo = { auth_enabled: true };
    authState.capabilities.browse = false;
    authState.principal = {
      ...authState.principal,
      kind: 'guest',
      authenticated: false,
      role: 'guest',
      capabilities: { ...authState.capabilities },
    };
  });

  it('redirects a guest to login', () => {
    renderRoute();
    expect(screen.getByText('Login screen')).toBeDefined();
  });

  it('redirects an authenticated principal without the required capability', () => {
    authState.isAuthenticated = true;
    authState.principal = { ...authState.principal, authenticated: true, kind: 'user', role: 'user' };

    renderRoute();

    expect(screen.getByText('Forbidden screen')).toBeDefined();
  });

  it('renders the protected outlet when the principal has the capability', () => {
    authState.isAuthenticated = true;
    authState.capabilities.browse = true;
    authState.principal = {
      ...authState.principal,
      authenticated: true,
      kind: 'user',
      role: 'user',
      capabilities: { ...authState.principal.capabilities, browse: true },
    };

    renderRoute();

    expect(screen.getByText('Browse screen')).toBeDefined();
  });

  it('allows a browse-capable guest when the server has no authentication configured', () => {
    authState.serverInfo = { auth_enabled: false };
    authState.capabilities.browse = true;
    authState.principal = {
      ...authState.principal,
      capabilities: { ...authState.principal.capabilities, browse: true },
    };

    renderRoute();

    expect(screen.getByText('Browse screen')).toBeDefined();
  });
});
