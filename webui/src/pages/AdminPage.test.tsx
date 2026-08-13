// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import AdminPage from './AdminPage';
import { QueryCacheProvider } from '../cache/QueryCacheContext';
import { setLang } from '../i18n';

const authState = vi.hoisted(() => ({
  role: 'admin',
  api: {},
  identityGeneration: 0,
}));

vi.mock('../hooks/useAuth', () => ({ useAuth: () => authState }));
vi.mock('../components/ui/Toast', () => ({ useToast: () => ({ showToast: vi.fn() }) }));
vi.mock('../hooks/useInvalidation', () => ({
  useInvalidation: () => ({ register: vi.fn(), unregister: vi.fn() }),
}));
vi.mock('../api/users', () => ({
  createUsersApi: () => ({
    list: vi.fn().mockResolvedValue({ users: [] }),
    toggleUser: vi.fn().mockResolvedValue({ ok: true }),
    listInvites: vi.fn().mockResolvedValue({ invites: [] }),
    createInvite: vi.fn().mockResolvedValue({ code: 'x' }),
    revokeInvite: vi.fn().mockResolvedValue({ ok: true }),
    getActivity: vi.fn().mockResolvedValue({ activities: [] }),
    getOnlineUsers: vi.fn().mockResolvedValue({ users: [] }),
  }),
}));
vi.mock('../api/shares', () => ({
  createSharesApi: () => ({
    list: vi.fn().mockResolvedValue({ shares: [] }),
    delete: vi.fn().mockResolvedValue({ ok: true }),
  }),
}));

describe('AdminPage', () => {
  afterEach(cleanup);

  it('renders the admin sections for an admin role', async () => {
    setLang('en');
    authState.role = 'admin';
    render(
      <QueryCacheProvider>
        <MemoryRouter>
          <AdminPage />
        </MemoryRouter>
      </QueryCacheProvider>,
    );
    expect(await screen.findByText('Admin Console')).toBeDefined();
    // Section headings repeat inside the child panels (both use admin.* keys).
    expect(screen.getAllByText('Users').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Invite Codes').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Share Links').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Activity Log').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Online Users').length).toBeGreaterThan(0);
    expect(screen.getByRole('link', { name: 'Back to library' })).toBeDefined();
  });

  it('renders nothing for a non-admin role (defensive fallback)', () => {
    authState.role = 'user';
    const { container } = render(
      <QueryCacheProvider>
        <MemoryRouter>
          <AdminPage />
        </MemoryRouter>
      </QueryCacheProvider>,
    );
    expect(container.firstChild).toBeNull();
  });
});
