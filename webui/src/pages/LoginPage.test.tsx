// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import LoginPage from './LoginPage';

let authMode: 'key' | 'password' = 'key';
let authLoading = false;
const authApi = {
  loginWithPassword: vi.fn(),
  verifyKey: vi.fn(),
};
const refreshMe = vi.fn();
const navigate = vi.fn();

vi.mock('../hooks/useAuth', () => ({
  useAuth: () => ({
    serverInfo: { auth_enabled: true, share_name: 'Library' },
    authMode,
    authApi,
    refreshMe,
    isLoading: authLoading,
  }),
}));
vi.mock('../hooks/useI18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }));
vi.mock('react-router-dom', async importOriginal => ({
  ...(await importOriginal<typeof import('react-router-dom')>()),
  useNavigate: () => navigate,
}));

describe('LoginPage registration policy', () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    authLoading = false;
    window.history.replaceState({}, '', '/login');
  });

  it('removes an auto-login key from the URL while preserving other location data', async () => {
    window.history.replaceState({}, '', '/login?key=secret&next=1#frag');
    authMode = 'key';
    authApi.verifyKey.mockResolvedValue({ ok: true });
    refreshMe.mockResolvedValue(false);

    render(<MemoryRouter><LoginPage /></MemoryRouter>);
    await waitFor(() => expect(authApi.verifyKey).toHaveBeenCalledWith('secret'));
    expect(`${window.location.pathname}${window.location.search}${window.location.hash}`).toBe('/login?next=1#frag');
  });

  it('exposes the auth-loading spinner as a status region', () => {
    authLoading = true;
    render(<MemoryRouter><LoginPage /></MemoryRouter>);
    expect(screen.getByRole('status', { name: 'landing.loading' })).toBeDefined();
  });

  it.each(['key', 'password'] as const)('hides registration in %s mode because the endpoint does not support it', mode => {
    authMode = mode;
    render(<MemoryRouter><LoginPage /></MemoryRouter>);
    expect(screen.queryByRole('button', { name: 'auth.no_account' })).toBeNull();
  });

  it('does not navigate after password login when the session refresh fails', async () => {
    authMode = 'password';
    authApi.loginWithPassword.mockResolvedValue({ ok: true });
    refreshMe.mockResolvedValue(false);
    const user = userEvent.setup();

    render(<MemoryRouter><LoginPage /></MemoryRouter>);
    await user.type(screen.getByPlaceholderText('auth.password_placeholder'), 'secret');
    await user.click(screen.getByRole('button', { name: 'auth.sign_in' }));

    expect(await screen.findByText('auth.login_failed')).toBeDefined();
    expect(navigate).not.toHaveBeenCalled();
  });

  it('does not navigate after key login when the session refresh fails', async () => {
    authMode = 'key';
    authApi.verifyKey.mockResolvedValue({ ok: true });
    refreshMe.mockResolvedValue(false);
    const user = userEvent.setup();

    render(<MemoryRouter><LoginPage /></MemoryRouter>);
    await user.type(screen.getByPlaceholderText('auth.key_placeholder'), 'access-key');
    await user.click(screen.getByRole('button', { name: 'auth.connect' }));

    expect(await screen.findByText('auth.invalid_key')).toBeDefined();
    expect(navigate).not.toHaveBeenCalled();
  });
});
