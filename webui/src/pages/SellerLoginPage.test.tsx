// @vitest-environment jsdom
import type { ReactNode } from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import SellerLoginPage from './SellerLoginPage';

const mocks = vi.hoisted(() => ({
  login: vi.fn(),
  showToast: vi.fn(),
}));

vi.mock('../stores/SellerAuthContext', () => ({
  useSellerAuth: () => ({ login: mocks.login }),
}));
vi.mock('../components/ui/Toast', () => ({
  useToast: () => ({ showToast: mocks.showToast }),
}));
vi.mock('../components/storefront/StorefrontShell', () => ({
  StorefrontShell: ({ children }: { children: ReactNode }) => <>{children}</>,
}));
vi.mock('../hooks/useI18n', () => ({
  useI18n: () => ({
    t: (key: string) => ({
      'seller.portal': 'Seller portal',
      'commerce.back_to_store': 'Back to store',
      'header.login': 'Log in',
      'auth.username': 'Username',
      'auth.password': 'Password',
      'seller.settings_subtitle': 'Manage your seller settings.',
      'browse.loading': 'Loading...',
    }[key] ?? key),
  }),
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/seller/login']}>
      <SellerLoginPage />
    </MemoryRouter>,
  );
}

function getForm() {
  return document.querySelector('form') as HTMLFormElement;
}

function getPasswordInput() {
  return document.getElementById('seller-password') as HTMLInputElement;
}

describe('SellerLoginPage', () => {
  beforeEach(() => {
    mocks.login.mockReset().mockResolvedValue(undefined);
    mocks.showToast.mockReset();
  });

  afterEach(() => cleanup());

  it('does not submit when the password is empty or whitespace-only', () => {
    renderPage();

    fireEvent.submit(getForm());
    expect(mocks.login).not.toHaveBeenCalled();

    fireEvent.change(getPasswordInput(), { target: { value: '   ' } });
    fireEvent.submit(getForm());
    expect(mocks.login).not.toHaveBeenCalled();
  });

  it('uses distinct accessible labels for username and password', () => {
    renderPage();

    expect(screen.getByLabelText('Username').getAttribute('id')).toBe('seller-username');
    expect(screen.getByLabelText('Password').getAttribute('id')).toBe('seller-password');
  });

  it('passes the password and username to login on success', async () => {
    renderPage();
    fireEvent.change(getPasswordInput(), { target: { value: 'seller-secret' } });

    fireEvent.submit(getForm());

    await waitFor(() => expect(mocks.login).toHaveBeenCalledWith('seller-secret', 'admin'));
    expect(mocks.showToast).not.toHaveBeenCalled();
  });

  it('prevents duplicate submissions while login is pending', async () => {
    const request = deferred<void>();
    mocks.login.mockReturnValue(request.promise);
    renderPage();
    fireEvent.change(getPasswordInput(), { target: { value: 'seller-secret' } });

    fireEvent.submit(getForm());
    fireEvent.submit(getForm());

    expect(mocks.login).toHaveBeenCalledTimes(1);
    expect((screen.getByRole('button', { name: 'Loading...' }) as HTMLButtonElement).disabled).toBe(true);

    await act(async () => request.resolve());
    await waitFor(() => expect((screen.getByRole('button', { name: 'Log in' }) as HTMLButtonElement).disabled).toBe(false));
  });

  it('shows the login error in an error toast and stops loading', async () => {
    const error = new Error('Invalid seller password');
    mocks.login.mockRejectedValue(error);
    renderPage();
    fireEvent.change(getPasswordInput(), { target: { value: 'wrong-password' } });

    fireEvent.submit(getForm());

    await waitFor(() => expect(mocks.showToast).toHaveBeenCalledWith('Invalid seller password', 'error'));
    expect((screen.getByRole('button', { name: 'Log in' }) as HTMLButtonElement).disabled).toBe(false);
  });

  it('uses the fallback error message for non-Error login failures', async () => {
    mocks.login.mockRejectedValue('request failed');
    renderPage();
    fireEvent.change(getPasswordInput(), { target: { value: 'seller-secret' } });

    fireEvent.submit(getForm());

    await waitFor(() => expect(mocks.showToast).toHaveBeenCalledWith('Seller login failed', 'error'));
  });
});


