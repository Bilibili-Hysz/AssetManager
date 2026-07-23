// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import LandingPage from './LandingPage';

const getHome = vi.fn();
let authState: {
  api: object;
  isAuthenticated: boolean;
  isLoading: boolean;
  role: 'user' | 'guest' | null;
  serverInfo: {
    auth_enabled: boolean;
    share_name: string;
    welcome_msg: string;
    library_stats: { total_projects: number; total_size: number; total_size_fmt: string };
  };
} = {
  api: {},
  isAuthenticated: true,
  isLoading: false,
  role: 'user' as const,
  serverInfo: {
    auth_enabled: true,
    share_name: 'Northstar Archive',
    welcome_msg: 'A private resource library.',
    library_stats: { total_projects: 12, total_size: 4096, total_size_fmt: '4 KB' },
  },
};

vi.mock('../hooks/useAuth', () => ({ useAuth: () => authState }));
vi.mock('../api/metadata', () => ({ createMetadataApi: () => ({ getHome }) }));
describe('LandingPage', () => {
  afterEach(() => {
    cleanup();
    getHome.mockReset();
    vi.unstubAllGlobals();
    localStorage.clear();
    authState = {
      ...authState,
      isAuthenticated: true,
      role: 'user',
      serverInfo: {
        auth_enabled: true,
        share_name: 'Northstar Archive',
        welcome_msg: 'A private resource library.',
        library_stats: { total_projects: 12, total_size: 4096, total_size_fmt: '4 KB' },
      },
    };
  });

  it('redirects unauthenticated users of protected libraries to login', () => {
    authState = { ...authState, isAuthenticated: false, role: null };

    render(
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route path="/" element={<LandingPage />} />
          <Route path="/login" element={<p>Login screen</p>} />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByText('Login screen')).toBeDefined();
  });

  it('redirects authenticated guest state of protected libraries to login', () => {
    authState = { ...authState, isAuthenticated: true, role: 'guest' };
    getHome.mockResolvedValue({ recent_projects: [], popular_tags: [], stats: { total_projects: 0, total_size: 0, total_size_fmt: '0 B' } });

    render(
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route path="/" element={<LandingPage />} />
          <Route path="/login" element={<p>Login screen</p>} />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByText('Login screen')).toBeDefined();
  });

  it('allows guests to access libraries with authentication disabled', async () => {
    authState = {
      ...authState,
      isAuthenticated: true,
      role: 'guest',
      serverInfo: { ...authState.serverInfo, auth_enabled: false },
    };
    getHome.mockResolvedValue({ recent_projects: [], popular_tags: [], stats: { total_projects: 0, total_size: 0, total_size_fmt: '0 B' } });

    render(<MemoryRouter><LandingPage /></MemoryRouter>);

    expect(await screen.findByRole('heading', { name: 'Northstar Archive' })).toBeDefined();
    expect(screen.getByRole('link', { name: 'Enter Library' }).getAttribute('href')).toBe('/browse');
  });

  it('shows server identity, featured assets, and the Browse entry action', async () => {
    getHome.mockResolvedValue({
      recent_projects: Array.from({ length: 7 }, (_, index) => ({
        name: `asset-${index + 1}.jpg`,
        path: `featured/asset-${index + 1}.jpg`,
        type: 'file',
        size: 1,
        size_fmt: '1 KB',
        modified: 0,
        extension: '.jpg',
        category: 'image',
        thumbnail_url: `/thumb/asset-${index + 1}.jpg`,
      })),
      popular_tags: [],
      stats: { total_projects: 7, total_size: 7, total_size_fmt: '7 KB' },
    });

    render(<MemoryRouter><LandingPage /></MemoryRouter>);

    expect(await screen.findByRole('heading', { name: 'Northstar Archive' })).toBeDefined();
    expect(screen.getByText('12 assets')).toBeDefined();
    expect(screen.getByRole('link', { name: 'Enter Library' }).getAttribute('href')).toBe('/browse');
    await waitFor(() => expect(screen.getAllByRole('img')).toHaveLength(6));
    expect(getHome).toHaveBeenCalledOnce();
  });

  it('aborts the home request when unmounted', () => {
    getHome.mockReturnValue(new Promise(() => {}));

    const { unmount } = render(<MemoryRouter><LandingPage /></MemoryRouter>);
    expect(getHome).toHaveBeenCalledOnce();
    const signal = getHome.mock.calls[0]![0] as AbortSignal;

    expect(signal.aborted).toBe(false);
    unmount();
    expect(signal.aborted).toBe(true);
  });

  it('removes only the failed featured tile when its thumbnail fails', async () => {
    getHome.mockResolvedValue({
      recent_projects: [{
        name: 'broken.jpg',
        path: 'featured/broken.jpg',
        type: 'file',
        size: 1,
        size_fmt: '1 KB',
        modified: 0,
        extension: '.jpg',
        category: 'image',
        thumbnail_url: '/thumb/broken.jpg',
      }],
      popular_tags: [],
      stats: { total_projects: 1, total_size: 1, total_size_fmt: '1 KB' },
    });

    render(<MemoryRouter><LandingPage /></MemoryRouter>);

    fireEvent.error(await screen.findByRole('img', { name: 'broken.jpg' }));
    await waitFor(() => expect(screen.queryByRole('img', { name: 'broken.jpg' })).toBeNull());
    expect(screen.queryByLabelText('Featured assets')).toBeNull();
  });

  it('shows an unavailable status while preserving library entry when featured assets fail to load', async () => {
    getHome.mockRejectedValue(new Error('Home request failed'));

    render(<MemoryRouter><LandingPage /></MemoryRouter>);

    expect(await screen.findByText('Library unavailable')).toBeDefined();
    expect(screen.queryByText('Library online')).toBeNull();
    expect(screen.getByRole('alert').textContent).toBe('Featured assets are unavailable. You can still enter the library.');
    expect(screen.getByRole('link', { name: 'Enter Library' }).getAttribute('href')).toBe('/browse');
  });

  it('opens and closes background tuning with accessible controls', () => {
    getHome.mockResolvedValue({ recent_projects: [], popular_tags: [], stats: { total_projects: 0, total_size: 0, total_size_fmt: '0 B' } });
    render(<MemoryRouter><LandingPage /></MemoryRouter>);

    const toggle = screen.getByRole('button', { name: 'Tune background' });
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    fireEvent.click(toggle);
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    const dialog = screen.getByRole('dialog', { name: 'Background tuning' });
    expect(dialog).toBeDefined();
    expect(dialog.className).toContain('max-h-[calc(100dvh-2rem)]');
    expect(dialog.className).toContain('overflow-y-auto');
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog', { name: 'Background tuning' })).toBeNull();
  });

  it('persists background tuning under a key scoped to the library theme', () => {
    const getItem = vi.fn(() => null);
    const setItem = vi.fn();
    const storage = { getItem, setItem, clear: vi.fn() };
    vi.stubGlobal('localStorage', storage);
    Object.defineProperty(window, 'localStorage', { configurable: true, value: storage });
    getHome.mockResolvedValue({ recent_projects: [], popular_tags: [], stats: { total_projects: 0, total_size: 0, total_size_fmt: '0 B' } });
    render(<MemoryRouter><LandingPage /></MemoryRouter>);

    fireEvent.click(screen.getByRole('button', { name: 'Tune background' }));
    const blur = screen.getByRole('slider', { name: /Blur/ });
    const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
    setValue.call(blur, '9');
    fireEvent.input(blur, { target: { value: '9' } });

    expect(setItem).toHaveBeenCalledWith('assets-manager.gate-background.default', JSON.stringify({
      blur: 9,
      brightness: 55,
      saturation: 75,
      opacity: 38,
    }));
  });
});
