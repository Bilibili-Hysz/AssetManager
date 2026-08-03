// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Link, MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ShareReceivePage from './ShareReceivePage';
import type { ShareInfoResponse } from '../types/api';

const { getInfo, verifyPassword, showToast, tMock } = vi.hoisted(() => ({
  getInfo: vi.fn(),
  verifyPassword: vi.fn(),
  showToast: vi.fn(),
  // Must be stable across renders: the page's effect depends on `t`, and an
  // unstable mock would restart getInfo on every render.
  tMock: (key: string) => key,
}));

vi.mock('../api/client', () => ({
  createApiClient: () => ({}),
}));
// Use the real createSharesApi so download/preview URL encoding is exercised,
// but override the network-backed methods with spies.
vi.mock('../api/shares', async importOriginal => {
  const actual = await importOriginal<typeof import('../api/shares')>();
  return {
    createSharesApi: (api: unknown) => ({
      ...actual.createSharesApi(api as never),
      getInfo,
      verifyPassword,
    }),
  };
});
vi.mock('../hooks/useTheme', () => ({ useTheme: () => {} }));
vi.mock('../components/ui/Toast', () => ({ useToast: () => ({ showToast }) }));
vi.mock('../hooks/useI18n', () => ({ useI18n: () => ({ t: tMock }) }));

const baseShare: ShareInfoResponse = {
  id: 'share-123',
  has_password: false,
  expired: false,
  allow_preview: false,
  paths: ['folder/file.txt'],
};

function renderPage(shareId = 'share-123') {
  return render(
    <MemoryRouter initialEntries={[`/s/${shareId}`]}>
      <Routes>
        <Route path="/s/:shareId" element={<ShareReceivePage />} />
      </Routes>
    </MemoryRouter>,
  );
}

function Harness() {
  return (
    <MemoryRouter initialEntries={['/s/share-a']}>
      <Link to="/s/share-b">to-share-b</Link>
      <Routes>
        <Route path="/s/:shareId" element={<ShareReceivePage />} />
      </Routes>
    </MemoryRouter>
  );
}

describe('ShareReceivePage', () => {
  beforeEach(() => {
    getInfo.mockReset();
    verifyPassword.mockReset();
    showToast.mockReset();
    getInfo.mockResolvedValue(baseShare);
  });

  afterEach(() => cleanup());

  it('shows a loading placeholder while fetching share info', async () => {
    let resolveInfo!: (value: ShareInfoResponse) => void;
    getInfo.mockReturnValueOnce(new Promise(resolve => { resolveInfo = resolve; }));

    renderPage();
    expect(screen.getByTestId('share-loading')).toBeDefined();

    resolveInfo(baseShare);
    expect(await screen.findByText('folder/file.txt')).toBeDefined();
    expect(screen.queryByTestId('share-loading')).toBeNull();
  });

  it('renders the file list returned by the public info endpoint', async () => {
    getInfo.mockResolvedValue({ ...baseShare, paths: ['folder/a.txt', 'folder/b/c.png'] });
    renderPage();

    expect(await screen.findByText('folder/a.txt')).toBeDefined();
    expect(screen.getByText('folder/b/c.png')).toBeDefined();
    expect(showToast).not.toHaveBeenCalled();
  });

  it('degrades to the not-found state and toasts when loading fails', async () => {
    getInfo.mockRejectedValue(new Error('HTTP 500'));
    renderPage();

    expect(await screen.findByText('share.not_found')).toBeDefined();
    expect(showToast).toHaveBeenCalledWith('share.failed_to_load', 'error');
  });

  it('shows an empty state when the share has no paths', async () => {
    getInfo.mockResolvedValue({ ...baseShare, paths: [] });
    renderPage();
    expect(await screen.findByText('share.no_files')).toBeDefined();
  });

  it('shows an empty state when paths are omitted', async () => {
    getInfo.mockResolvedValue({ ...baseShare, paths: undefined });
    renderPage();
    expect(await screen.findByText('share.no_files')).toBeDefined();
  });

  it('shows an expired state when the share has expired', async () => {
    getInfo.mockResolvedValue({ ...baseShare, expired: true, paths: ['folder/file.txt'] });
    renderPage();
    expect(await screen.findByText('share.expired')).toBeDefined();
    expect(screen.queryByText('folder/file.txt')).toBeNull();
  });

  it('requires a password for a protected share without cookie-authorized paths', async () => {
    getInfo.mockResolvedValue({ ...baseShare, has_password: true, paths: undefined });
    renderPage();

    expect(await screen.findByText('share.password_required')).toBeDefined();
    expect(screen.queryByText('share.title')).toBeNull();
  });

  it('skips the password gate when the info response already carries paths', async () => {
    getInfo.mockResolvedValue({ ...baseShare, has_password: true, paths: ['folder/file.txt'] });
    renderPage();

    expect(await screen.findByText('folder/file.txt')).toBeDefined();
    expect(screen.queryByText('share.password_required')).toBeNull();
  });

  it('verifies a password successfully and reveals the file list', async () => {
    getInfo.mockResolvedValue({ ...baseShare, has_password: true, paths: undefined });
    verifyPassword.mockResolvedValue({
      share: {
        id: 'share-123', paths: ['folder/file.txt'], created_by: 'user',
        created_at: 0, allow_preview: false, download_count: 0, max_downloads: null,
        has_password: true, expired: false, expires_in_hours: null,
      },
    });
    const user = userEvent.setup();
    renderPage();

    await user.type(await screen.findByPlaceholderText('share.password'), 'secret');
    await user.click(screen.getByRole('button', { name: 'share.verify_btn' }));

    expect(verifyPassword).toHaveBeenCalledWith('share-123', 'secret');
    expect(await screen.findByText('folder/file.txt')).toBeDefined();
  });

  it('toasts an invalid password and stays on the password form', async () => {
    getInfo.mockResolvedValue({ ...baseShare, has_password: true, paths: undefined });
    verifyPassword.mockRejectedValue(new Error('Invalid password'));
    const user = userEvent.setup();
    renderPage();

    await user.type(await screen.findByPlaceholderText('share.password'), 'wrong');
    await user.click(screen.getByRole('button', { name: 'share.verify_btn' }));

    expect(await screen.findByText('share.password_required')).toBeDefined();
    expect(showToast).toHaveBeenCalledWith('share.invalid_password', 'error');
    expect(screen.queryByText('share.title')).toBeNull();
  });

  it('encodes download and preview URLs segment by segment', async () => {
    getInfo.mockResolvedValue({
      ...baseShare,
      allow_preview: true,
      paths: ['目录/子 文件.svg'],
    });
    renderPage();

    const download = await screen.findByRole('link', { name: 'share.download' });
    expect(download.getAttribute('href')).toBe(
      '/api/shares/share-123/download/%E7%9B%AE%E5%BD%95/%E5%AD%90%20%E6%96%87%E4%BB%B6.svg',
    );
    const preview = screen.getByRole('link', { name: 'share.preview' });
    expect(preview.getAttribute('href')).toBe(
      '/api/shares/share-123/preview/%E7%9B%AE%E5%BD%95/%E5%AD%90%20%E6%96%87%E4%BB%B6.svg',
    );
  });

  it('only renders preview links when the share allows preview', async () => {
    getInfo.mockResolvedValue({ ...baseShare, allow_preview: false });
    renderPage();

    await screen.findByText('folder/file.txt');
    expect(screen.queryByRole('link', { name: 'share.preview' })).toBeNull();
    expect(screen.getByRole('link', { name: 'share.download' })).toBeDefined();
  });

  it('prevents duplicate password verification submissions', async () => {
    getInfo.mockResolvedValue({ ...baseShare, has_password: true, paths: undefined });
    let resolveVerify!: (value: { share: ShareInfoResponse & { paths: string[] } }) => void;
    verifyPassword.mockReturnValueOnce(new Promise(resolve => { resolveVerify = resolve; }));
    const user = userEvent.setup();
    renderPage();

    await user.type(await screen.findByPlaceholderText('share.password'), 'secret');
    const button = screen.getByRole('button', { name: 'share.verify_btn' });
    await user.click(button);
    expect(verifyPassword).toHaveBeenCalledTimes(1);

    await user.click(button);
    expect(verifyPassword).toHaveBeenCalledTimes(1);

    resolveVerify({
      share: { ...baseShare, has_password: true, paths: ['folder/file.txt'] },
    });
    expect(await screen.findByText('folder/file.txt')).toBeDefined();
  });

  it('ignores a stale info response after navigating to another share', async () => {
    let resolveFirst!: (value: ShareInfoResponse) => void;
    getInfo.mockReturnValueOnce(new Promise(resolve => { resolveFirst = resolve; }));
    getInfo.mockResolvedValue({ ...baseShare, id: 'share-b', paths: ['second.txt'] });
    const user = userEvent.setup();

    render(<Harness />);
    await waitFor(() => expect(getInfo).toHaveBeenCalledTimes(1));

    await user.click(screen.getByRole('link', { name: 'to-share-b' }));
    await waitFor(() => expect(getInfo).toHaveBeenCalledTimes(2));

    resolveFirst({ ...baseShare, id: 'share-a', paths: ['stale.txt'] });
    expect(screen.queryByText('stale.txt')).toBeNull();
    expect(await screen.findByText('second.txt')).toBeDefined();
  });
});
