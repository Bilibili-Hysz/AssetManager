// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import LoginPage from './LoginPage';

let authMode: 'key' | 'password' = 'key';

vi.mock('../hooks/useAuth', () => ({
  useAuth: () => ({
    serverInfo: { auth_enabled: true, share_name: 'Library' },
    authMode,
    authApi: {},
    setToken: vi.fn(),
    isLoading: false,
  }),
}));
vi.mock('../hooks/useI18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }));

describe('LoginPage registration policy', () => {
  afterEach(cleanup);

  it.each(['key', 'password'] as const)('offers registration in %s mode because the endpoint permits it', mode => {
    authMode = mode;
    render(<MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><LoginPage /></MemoryRouter>);
    expect(screen.getByRole('button', { name: 'auth.no_account' })).toBeDefined();
  });
});
