// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import LandingPage from './LandingPage';
import { QueryCacheProvider } from '../cache/QueryCacheContext';

const getHome = vi.fn();
const { useInvalidationMock } = vi.hoisted(() => ({ useInvalidationMock: vi.fn() }));
let authState: {
  api: object;
  isAuthenticated: boolean;
  isLoading: boolean;
  role: 'user' | 'guest' | null;
  serverInfo: {
    auth_enabled: boolean;
    share_name: string;
    welcome_msg: string;
    theme_color: string;
    footer_text: string;
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
    theme_color: '#6366f1',
    footer_text: 'Local service · Ready when you are.',
    library_stats: { total_projects: 12, total_size: 4096, total_size_fmt: '4 KB' },
  },
};

vi.mock('../hooks/useAuth', () => ({ useAuth: () => authState }));
vi.mock('../api/metadata', () => ({ createMetadataApi: () => ({ getHome }) }));
vi.mock('../hooks/useInvalidation', () => ({
  useInvalidation: useInvalidationMock,
}));

function LandingApp() {
  return <QueryCacheProvider><LandingPage /></QueryCacheProvider>;
}

describe('LandingPage', () => {
  beforeEach(() => {
    localStorage.setItem('am_theme', 'dark');
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    getHome.mockReset();
    useInvalidationMock.mockReset();
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
        theme_color: '#6366f1',
        footer_text: 'Local service · Ready when you are.',
        library_stats: { total_projects: 12, total_size: 4096, total_size_fmt: '4 KB' },
      },
    };
  });

  it('redirects unauthenticated users of protected libraries to login', () => {
    authState = { ...authState, isAuthenticated: false, role: null };

    render(
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route path="/" element={<LandingApp />} />
          <Route path="/login" element={<p>Login screen</p>} />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByText('Login screen')).toBeDefined();
  });

  it('redirects authenticated guest state of protected libraries to login', () => {
    authState = { ...authState, isAuthenticated: true, role: 'guest' };
    getHome.mockResolvedValue({ recent_projects: [], preview_pool: [], popular_tags: [], stats: { total_projects: 0, total_size: 0, total_size_fmt: '0 B' } });

    render(
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route path="/" element={<LandingApp />} />
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
    getHome.mockResolvedValue({ recent_projects: [], preview_pool: [], popular_tags: [], stats: { total_projects: 0, total_size: 0, total_size_fmt: '0 B' } });

    render(<MemoryRouter><LandingApp /></MemoryRouter>);

    expect(await screen.findByRole('heading', { name: 'Northstar Archive' })).toBeDefined();
    // The heading renders synchronously from serverInfo; the empty-library
    // message only appears once the async Home data resolves, so await it.
    expect(await screen.findByText('No images found in this library.')).toBeDefined();
    expect(screen.getByRole('link', { name: 'Enter Gallery to discover visual assets' }).getAttribute('href')).toBe('/gallery');
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
         thumbnail_url: `/api/thumbnails/featured%2Fasset-${index + 1}.jpg`,
      })),
      preview_pool: Array.from({ length: 7 }, (_, index) => ({
        name: `asset-${index + 1}.jpg`, path: `featured/asset-${index + 1}.jpg`, type: 'file', size: 1, size_fmt: '1 KB', modified: 0, extension: '.jpg', category: 'image',
        thumbnail_url: `/api/thumbnails/featured%2Fasset-${index + 1}.jpg`,
      })),
      popular_tags: [],
      stats: { total_projects: 7, total_size: 7, total_size_fmt: '7 KB' },
    });

    render(<MemoryRouter><LandingApp /></MemoryRouter>);

    expect(await screen.findByRole('heading', { name: 'Northstar Archive' })).toBeDefined();
    // The heading renders synchronously from serverInfo, but the asset count
    // only switches from the library_stats fallback ("12 assets") to the Home
    // stats ("7 assets") after the async Home response resolves — so await it.
    expect(await screen.findByText(/7 assets/)).toBeDefined();
    expect(screen.getByRole('link', { name: 'Enter Gallery to discover visual assets' }).getAttribute('href')).toBe('/gallery');
    await waitFor(() => expect(screen.getAllByTestId('gate-showcase-image')).toHaveLength(6));
    expect(getHome).toHaveBeenCalledWith(expect.any(AbortSignal));
  });

  it('registers only the home projection domain', async () => {
    getHome.mockResolvedValue({ recent_projects: [], preview_pool: [], popular_tags: [], stats: { total_projects: 0, total_size: 0, total_size_fmt: '0 B' } });
    render(<MemoryRouter><LandingApp /></MemoryRouter>);
    await waitFor(() => expect(useInvalidationMock.mock.calls[0]?.[0]).toEqual(['home']));
  });

  it('uses only the standard reduced-motion media listener when available', async () => {
    const mediaQuery = {
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
    };
    vi.stubGlobal('matchMedia', vi.fn(() => mediaQuery));
    getHome.mockResolvedValue({ recent_projects: [], preview_pool: [], popular_tags: [], stats: { total_projects: 0, total_size: 0, total_size_fmt: '0 B' } });

    const { unmount } = render(<MemoryRouter><LandingApp /></MemoryRouter>);
    await waitFor(() => expect(mediaQuery.addEventListener).toHaveBeenCalled());
    expect(mediaQuery.addListener).not.toHaveBeenCalled();

    unmount();
    expect(mediaQuery.removeEventListener).toHaveBeenCalled();
    expect(mediaQuery.removeListener).not.toHaveBeenCalled();
  });

  it('falls back to recent projects when the legacy Home response omits preview_pool', async () => {
    getHome.mockResolvedValue({
      recent_projects: [{
        name: 'legacy-featured.jpg',
        path: 'legacy/legacy-featured.jpg',
        type: 'file',
        size: 1,
        size_fmt: '1 KB',
        modified: 0,
        extension: '.jpg',
        category: 'image',
        thumbnail_url: '/api/thumbnails/legacy%2Flegacy-featured.jpg',
      }],
      popular_tags: [],
      stats: { total_projects: 1, total_size: 1, total_size_fmt: '1 KB' },
    });

    render(<MemoryRouter><LandingApp /></MemoryRouter>);

    expect(await screen.findByLabelText('Featured assets')).toBeDefined();
    expect(screen.getByTestId('gate-showcase-image').getAttribute('data-src')).toBe('/api/thumbnails/legacy%2Flegacy-featured.jpg');
  });

  it('does not fall back to recent projects when preview_pool is explicitly empty', async () => {
    getHome.mockResolvedValue({
      recent_projects: [{
        name: 'recent-only.jpg',
        path: 'recent/recent-only.jpg',
        type: 'file',
        size: 1,
        size_fmt: '1 KB',
        modified: 0,
        extension: '.jpg',
        category: 'image',
        thumbnail_url: '/api/thumbnails/recent%2Frecent-only.jpg',
      }],
      preview_pool: [],
      popular_tags: [],
      stats: { total_projects: 1, total_size: 1, total_size_fmt: '1 KB' },
    });

    render(<MemoryRouter><LandingApp /></MemoryRouter>);

    expect(await screen.findByText('No images found in this library.')).toBeDefined();
    expect(screen.queryByLabelText('Featured assets')).toBeNull();
    expect(screen.queryByTestId('gate-showcase-image')).toBeNull();
  });

  it('uses preview_pool for Gate candidates and stats.total_projects for assets', async () => {
    const recentProject = {
      name: 'recent.jpg', path: 'recent.jpg', type: 'file' as const, size: 1, size_fmt: '1 B', modified: 0,
      extension: '.jpg', category: 'image', thumbnail_url: '/api/thumbnails/recent.jpg',
    };
    const fullLibraryProject = {
      name: 'full-library.jpg', path: 'archive/full-library.jpg', type: 'file' as const, size: 1, size_fmt: '1 B', modified: 0,
      extension: '.jpg', category: 'image', thumbnail_url: '/api/thumbnails/archive%2Ffull-library.jpg',
    };
    getHome.mockResolvedValue({
      recent_projects: [recentProject],
      preview_pool: [recentProject, fullLibraryProject],
      popular_tags: [],
      stats: { total_projects: 1518, total_size: 7, total_size_fmt: '7 KB' },
    });

    render(<MemoryRouter><LandingApp /></MemoryRouter>);

    await waitFor(() => expect(screen.getByRole('status').textContent).toContain('1518 artworks'));
    await waitFor(() => expect(screen.getAllByTestId('gate-showcase-image')).toHaveLength(2));
    expect(screen.getAllByTestId('gate-showcase-image').map(image => image.getAttribute('data-src'))).toEqual(expect.arrayContaining([
      '/api/thumbnails/archive%2Ffull-library.jpg',
    ]));
  });

  it('uses Home stats as the authoritative online Gate statistics', async () => {
    authState = {
      ...authState,
      serverInfo: {
        ...authState.serverInfo,
        library_stats: { total_projects: 999, total_size: 999, total_size_fmt: '999 KB' },
      },
    };
    getHome.mockResolvedValue({
      recent_projects: [],
      preview_pool: [],
      popular_tags: [],
      stats: { total_projects: 1518, total_size: 1518, total_size_fmt: '1518 KB' },
    });

    render(<MemoryRouter><LandingApp /></MemoryRouter>);

    await waitFor(() => expect(screen.getByRole('status').textContent).toContain('1518 artworks'));
    expect(screen.getByText(/1518 assets · 1518 KB/)).toBeDefined();
    expect(screen.queryByText(/999 assets/)).toBeNull();
  });

  it('builds the preview pool from non-empty thumbnail URLs and removes duplicate URLs', async () => {
    vi.spyOn(Math, 'random').mockReturnValue(0.5);
    getHome.mockResolvedValue({
      recent_projects: [
        { name: 'missing', path: 'missing.jpg', type: 'file', size: 1, size_fmt: '1 B', modified: 0, extension: '.jpg', category: 'image', thumbnail_url: '' },
        { name: 'first', path: 'first.jpg', type: 'file', size: 1, size_fmt: '1 B', modified: 0, extension: '.jpg', category: 'image', thumbnail_url: ' /api/thumbnails/first.jpg ' },
        { name: 'duplicate', path: 'duplicate.jpg', type: 'file', size: 1, size_fmt: '1 B', modified: 0, extension: '.jpg', category: 'image', thumbnail_url: '/api/thumbnails/first.jpg' },
        { name: 'second', path: 'second.jpg', type: 'file', size: 1, size_fmt: '1 B', modified: 0, extension: '.jpg', category: 'image', thumbnail_url: '/api/thumbnails/second.jpg' },
      ],
      preview_pool: [
        { name: 'missing', path: 'missing.jpg', type: 'file', size: 1, size_fmt: '1 B', modified: 0, extension: '.jpg', category: 'image', thumbnail_url: '' },
        { name: 'first', path: 'first.jpg', type: 'file', size: 1, size_fmt: '1 B', modified: 0, extension: '.jpg', category: 'image', thumbnail_url: ' /api/thumbnails/first.jpg ' },
        { name: 'duplicate', path: 'duplicate.jpg', type: 'file', size: 1, size_fmt: '1 B', modified: 0, extension: '.jpg', category: 'image', thumbnail_url: '/api/thumbnails/first.jpg' },
        { name: 'second', path: 'second.jpg', type: 'file', size: 1, size_fmt: '1 B', modified: 0, extension: '.jpg', category: 'image', thumbnail_url: '/api/thumbnails/second.jpg' },
      ],
      popular_tags: [],
      stats: { total_projects: 4, total_size: 4, total_size_fmt: '4 B' },
    });

    render(<MemoryRouter><LandingApp /></MemoryRouter>);

    await waitFor(() => expect(screen.getAllByTestId('gate-showcase-image')).toHaveLength(2));
    expect(new Set(screen.getAllByTestId('gate-showcase-image').map(image => image.getAttribute('data-src')))).toEqual(new Set([
      '/api/thumbnails/first.jpg',
      '/api/thumbnails/second.jpg',
    ]));
    expect(screen.queryByRole('img', { name: 'missing' })).toBeNull();
  });

  it('preloads the initial showcase and wall candidates after Home succeeds', async () => {
    const imageInstances: Array<{ src: string; addEventListener: ReturnType<typeof vi.fn>; removeEventListener: ReturnType<typeof vi.fn> }> = [];
    vi.stubGlobal('Image', vi.fn(function ImageMock(this: { src: string; addEventListener: ReturnType<typeof vi.fn>; removeEventListener: ReturnType<typeof vi.fn> }) {
      this.src = '';
      this.addEventListener = vi.fn();
      this.removeEventListener = vi.fn();
      imageInstances.push(this);
    }));
    getHome.mockResolvedValue({
      recent_projects: Array.from({ length: 7 }, (_, index) => ({
        name: `asset-${index + 1}.jpg`, path: `asset-${index + 1}.jpg`, type: 'file', size: 1, size_fmt: '1 B', modified: 0, extension: '.jpg', category: 'image',
        thumbnail_url: `/api/thumbnails/asset-${index + 1}.jpg`,
      })),
      preview_pool: Array.from({ length: 7 }, (_, index) => ({
        name: `asset-${index + 1}.jpg`, path: `asset-${index + 1}.jpg`, type: 'file', size: 1, size_fmt: '1 B', modified: 0, extension: '.jpg', category: 'image',
        thumbnail_url: `/api/thumbnails/asset-${index + 1}.jpg`,
      })),
      popular_tags: [],
      stats: { total_projects: 7, total_size: 7, total_size_fmt: '7 KB' },
    });

    render(<MemoryRouter><LandingApp /></MemoryRouter>);

    await waitFor(() => expect(imageInstances).toHaveLength(7));
    expect(imageInstances.map(image => image.src)).toEqual(expect.arrayContaining(
      Array.from({ length: 7 }, (_, index) => `/api/thumbnails/asset-${index + 1}.jpg`),
    ));
  });

  it('replaces a showcase item only after the next image preloads', async () => {
    vi.useFakeTimers();
    const imageInstances: Array<{ src: string; onload: (() => void) | null; onerror: (() => void) | null; addEventListener: ReturnType<typeof vi.fn>; removeEventListener: ReturnType<typeof vi.fn> }> = [];
    vi.stubGlobal('Image', vi.fn(function ImageMock(this: (typeof imageInstances)[number]) {
      this.src = '';
      this.onload = null;
      this.onerror = null;
      this.addEventListener = vi.fn();
      this.removeEventListener = vi.fn();
      imageInstances.push(this);
    }));
    getHome.mockResolvedValue({
      recent_projects: Array.from({ length: 7 }, (_, index) => ({
        name: `asset-${index + 1}.jpg`, path: `asset-${index + 1}.jpg`, type: 'file', size: 1, size_fmt: '1 B', modified: 0, extension: '.jpg', category: 'image', thumbnail_url: `/api/thumbnails/asset-${index + 1}.jpg`,
      })),
      preview_pool: Array.from({ length: 7 }, (_, index) => ({
        name: `asset-${index + 1}.jpg`, path: `asset-${index + 1}.jpg`, type: 'file', size: 1, size_fmt: '1 B', modified: 0, extension: '.jpg', category: 'image', thumbnail_url: `/api/thumbnails/asset-${index + 1}.jpg`,
      })),
      popular_tags: [],
      stats: { total_projects: 7, total_size: 7, total_size_fmt: '7 KB' },
    });

    render(<MemoryRouter><LandingApp /></MemoryRouter>);
    await act(async () => { await Promise.resolve(); });
    expect(screen.getAllByTestId('gate-showcase-image')).toHaveLength(6);
    const initial = screen.getAllByTestId('gate-showcase-image').map(image => image.getAttribute('data-src'));

    vi.advanceTimersByTime(20_000);
    expect(screen.getAllByTestId('gate-showcase-image').map(image => image.getAttribute('data-src'))).toEqual(initial);
    const replacement = imageInstances.find(image => !initial.includes(image.src) && image.onload);
    expect(replacement).toBeDefined();
    await act(async () => {
      replacement?.onload?.();
      await Promise.resolve();
    });
    expect(screen.getAllByTestId('gate-showcase-image').map(image => image.getAttribute('data-src'))).not.toEqual(initial);
  });

  it('suppresses pointer effects when reduced motion is enabled', () => {
    vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
    getHome.mockResolvedValue({ recent_projects: [], preview_pool: [], popular_tags: [], stats: { total_projects: 0, total_size: 0, total_size_fmt: '0 B' } });

    render(<MemoryRouter><LandingApp /></MemoryRouter>);
    fireEvent.pointerMove(screen.getByRole('main'), { pointerType: 'mouse', clientX: 40, clientY: 40 });
    fireEvent.pointerDown(screen.getByRole('main'), { pointerType: 'mouse', clientX: 40, clientY: 40 });

    expect(document.querySelectorAll('.gate-particle')).toHaveLength(0);
    expect(document.querySelectorAll('.gate-ripple')).toHaveLength(0);
  });

  it('suppresses pointer effects while the page is hidden', () => {
    getHome.mockResolvedValue({ recent_projects: [], preview_pool: [], popular_tags: [], stats: { total_projects: 0, total_size: 0, total_size_fmt: '0 B' } });
    render(<MemoryRouter><LandingApp /></MemoryRouter>);

    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' });
    fireEvent(document, new Event('visibilitychange'));
    expect(screen.getByRole('main').className).toContain('gate-paused');
    fireEvent.pointerMove(screen.getByRole('main'), { pointerType: 'mouse', clientX: 40, clientY: 40 });
    fireEvent.pointerDown(screen.getByRole('main'), { pointerType: 'mouse', clientX: 40, clientY: 40 });

    expect(document.querySelectorAll('.gate-particle')).toHaveLength(0);
    expect(document.querySelectorAll('.gate-ripple')).toHaveLength(0);
  });

  it('uses the stable shuffled preview pool for both wall and showcase', async () => {
    vi.spyOn(Math, 'random').mockReturnValue(0.99);
    getHome.mockResolvedValue({
      recent_projects: Array.from({ length: 7 }, (_, index) => ({
        name: `asset-${index + 1}.jpg`, path: `asset-${index + 1}.jpg`, type: 'file', size: 1, size_fmt: '1 B', modified: 0, extension: '.jpg', category: 'image',
        thumbnail_url: `/api/thumbnails/asset-${index + 1}.jpg`,
      })),
      preview_pool: Array.from({ length: 7 }, (_, index) => ({
        name: `asset-${index + 1}.jpg`, path: `asset-${index + 1}.jpg`, type: 'file', size: 1, size_fmt: '1 B', modified: 0, extension: '.jpg', category: 'image',
        thumbnail_url: `/api/thumbnails/asset-${index + 1}.jpg`,
      })),
      popular_tags: [],
      stats: { total_projects: 7, total_size: 7, total_size_fmt: '7 B' },
    });

    render(<MemoryRouter><LandingApp /></MemoryRouter>);
    await waitFor(() => expect(screen.getAllByTestId('gate-showcase-image')).toHaveLength(6));

    const initialShowcase = screen.getAllByTestId('gate-showcase-image').map(image => image.getAttribute('data-src'));
    const wallImages = Array.from(document.querySelectorAll('.gate-image-wall img')).map(image => image.getAttribute('src')).filter(Boolean);
    expect(new Set(wallImages)).toEqual(new Set(Array.from({ length: 7 }, (_, index) => `/api/thumbnails/asset-${index + 1}.jpg`)));
    expect(initialShowcase.every(url => wallImages.includes(url))).toBe(true);

    fireEvent.click(screen.getByRole('button', { name: /switch to light theme/i }));
    expect(screen.getAllByTestId('gate-showcase-image').map(image => image.getAttribute('data-src'))).toEqual(initialShowcase);
    expect(Math.random).toHaveBeenCalledTimes(6);
  });

  it('renders the complete Gate hierarchy from AssetManager values', async () => {
    getHome.mockResolvedValue({
      recent_projects: [{
        name: 'Portrait', path: 'portraits/one.png', type: 'file', size: 12,
        size_fmt: '12 B', modified: 1, extension: '.png', category: 'image',
        thumbnail_url: '/api/thumbnails/portraits%2Fone.png',
      }],
      preview_pool: [{
        name: 'Portrait', path: 'portraits/one.png', type: 'file', size: 12,
        size_fmt: '12 B', modified: 1, extension: '.png', category: 'image',
        thumbnail_url: '/api/thumbnails/portraits%2Fone.png',
      }],
      popular_tags: [],
      stats: { total_projects: 1, total_size: 12, total_size_fmt: '12 B' },
    });

    render(<MemoryRouter><LandingApp /></MemoryRouter>);

    expect(await screen.findByRole('heading', { name: 'Northstar Archive' })).toBeDefined();
    expect(screen.getByText('Designer')).toBeDefined();
    expect(screen.getByRole('button', { name: /switch to light theme/i })).toBeDefined();
    expect(screen.getByRole('button', { name: 'Background tuning' }).getAttribute('aria-controls')).toBe('background-tuning');
    expect(screen.getByRole('link', { name: 'Enter Gallery to discover visual assets' }).getAttribute('href')).toBe('/gallery');
    expect(screen.getByText(/Local service · Ready when you are\./)).toBeDefined();
    expect((await screen.findByTestId('gate-showcase-image')).getAttribute('data-src')).toBe('/api/thumbnails/portraits%2Fone.png');
  });

  it('renders the workspace entry as one secondary link carrying title and description', async () => {
    getHome.mockResolvedValue({ recent_projects: [], preview_pool: [], popular_tags: [], stats: { total_projects: 0, total_size: 0, total_size_fmt: '0 B' } });

    render(<MemoryRouter><LandingApp /></MemoryRouter>);

    // The whole option card is a single /browse link whose accessible name
    // includes both the title and the description; the old structure rendered
    // an unstyled copy block plus a duplicate bare "Open Workspace" link.
    const option = await screen.findByRole('link', { name: /Open Workspace Search folders/ });
    expect(option.getAttribute('href')).toBe('/browse');
    expect(option.className).toContain('gate-workspace-option');
    expect(screen.getAllByRole('link', { name: /Open Workspace/ })).toHaveLength(1);
  });

  it('aborts the home request when unmounted', () => {
    getHome.mockReturnValue(new Promise(() => {}));

    const { unmount } = render(<MemoryRouter><LandingApp /></MemoryRouter>);
    expect(getHome).toHaveBeenCalledOnce();
    const signal = getHome.mock.calls[0]![0] as AbortSignal;

    expect(signal.aborted).toBe(false);
    unmount();
    expect(signal.aborted).toBe(true);
  });

  it('keeps a failed featured tile with the layered folder fallback', async () => {
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
      preview_pool: [{
        name: 'broken.jpg', path: 'featured/broken.jpg', type: 'file', size: 1,
        size_fmt: '1 KB', modified: 0, extension: '.jpg', category: 'image', thumbnail_url: '/thumb/broken.jpg',
      }],
      popular_tags: [],
      stats: { total_projects: 1, total_size: 1, total_size_fmt: '1 KB' },
    });

    render(<MemoryRouter><LandingApp /></MemoryRouter>);

    const image = await screen.findByRole('img', { name: 'broken.jpg' });
    expect(screen.getAllByTestId('layered-preview-back')).toHaveLength(2);
    fireEvent.error(image);

    await waitFor(() => expect(screen.getByLabelText('Featured assets')).toBeDefined());
    expect(screen.getByTestId('layered-preview-folder')).toBeDefined();
    expect(screen.queryByRole('img', { name: 'broken.jpg' })).toBeNull();
  });

  it('shows an unavailable status while preserving library entry when featured assets fail to load', async () => {
    getHome.mockRejectedValue(new Error('Home request failed'));

    render(<MemoryRouter><LandingApp /></MemoryRouter>);

    expect(await screen.findByText('Library unavailable')).toBeDefined();
    expect(screen.queryByText('Library online', { selector: '.sr-only' })).toBeNull();
    expect(screen.getByRole('alert').textContent).toBe('Featured assets are unavailable. You can still enter the library.');
    expect(screen.getByRole('link', { name: 'Enter Gallery to discover visual assets' }).getAttribute('href')).toBe('/gallery');
  });

  it('opens and closes background tuning with accessible controls', () => {
    getHome.mockResolvedValue({ recent_projects: [], popular_tags: [], stats: { total_projects: 0, total_size: 0, total_size_fmt: '0 B' } });
    render(<MemoryRouter><LandingApp /></MemoryRouter>);

    const toggle = screen.getByRole('button', { name: 'Background tuning' });
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
    render(<MemoryRouter><LandingApp /></MemoryRouter>);

    fireEvent.click(screen.getByRole('button', { name: 'Background tuning' }));
    const blur = screen.getByRole('slider', { name: /Blur/ });
    const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
    setValue.call(blur, '9');
    fireEvent.input(blur, { target: { value: '9' } });

    expect(setItem).toHaveBeenCalledWith('assets-manager.gate-background.#6366f1', JSON.stringify({
      light: {
        blur: 9,
        brightness: 100,
        saturation: 85,
        canvasOpacity: 55,
        itemOpacity: 60,
      },
    }));
  });

  it('removes an expired particle timer from the effect timer bookkeeping', () => {
    vi.useFakeTimers();
    getHome.mockResolvedValue({ recent_projects: [], preview_pool: [], popular_tags: [], stats: { total_projects: 0, total_size: 0, total_size_fmt: '0 B' } });

    render(<MemoryRouter><LandingApp /></MemoryRouter>);
    const baselineTimers = vi.getTimerCount();
    fireEvent.pointerMove(screen.getByRole('main'), { pointerType: 'mouse', clientX: 20, clientY: 30 });
    expect(vi.getTimerCount()).toBe(baselineTimers + 3);

    vi.advanceTimersByTime(805);
    expect(vi.getTimerCount()).toBe(baselineTimers);
  });

  it('keeps only live ripple timers in the effect timer bookkeeping', () => {
    vi.useFakeTimers();
    getHome.mockResolvedValue({ recent_projects: [], preview_pool: [], popular_tags: [], stats: { total_projects: 0, total_size: 0, total_size_fmt: '0 B' } });

    render(<MemoryRouter><LandingApp /></MemoryRouter>);
    const baselineTimers = vi.getTimerCount();
    fireEvent.pointerDown(screen.getByRole('main'), { pointerType: 'mouse', clientX: 20, clientY: 30 });
    expect(vi.getTimerCount()).toBe(baselineTimers + 2);

    vi.advanceTimersByTime(780);
    expect(vi.getTimerCount()).toBe(baselineTimers + 1);
    vi.advanceTimersByTime(200);
    expect(vi.getTimerCount()).toBe(baselineTimers);
  });

  it('renders and positions a cursor glow for mouse movement', async () => {
    getHome.mockResolvedValue({ recent_projects: [], preview_pool: [], popular_tags: [], stats: { total_projects: 0, total_size: 0, total_size_fmt: '0 B' } });

    render(<MemoryRouter><LandingApp /></MemoryRouter>);
    const pointerMove = new Event('pointermove', { bubbles: true });
    Object.assign(pointerMove, { pointerType: 'mouse', clientX: 84, clientY: 126 });
    fireEvent(screen.getByRole('main'), pointerMove);

    await waitFor(() => {
      const glow = document.querySelector<HTMLElement>('.gate-cursor-glow');
      expect(glow?.style.left).toBe('84px');
      expect(glow?.style.top).toBe('126px');
    });
  });

  it('gives body-level pointer particles a resolved effect color', () => {
    getHome.mockResolvedValue({ recent_projects: [], preview_pool: [], popular_tags: [], stats: { total_projects: 0, total_size: 0, total_size_fmt: '0 B' } });

    render(<MemoryRouter><LandingApp /></MemoryRouter>);
    fireEvent.pointerMove(screen.getByRole('main'), { pointerType: 'mouse', clientX: 84, clientY: 126 });

    expect(document.querySelector<HTMLElement>('.gate-particle')?.style.getPropertyValue('--gate-effect-color')).toBeTruthy();
  });

  it('emits a visible particle trail for a mouse movement', () => {
    getHome.mockResolvedValue({ recent_projects: [], preview_pool: [], popular_tags: [], stats: { total_projects: 0, total_size: 0, total_size_fmt: '0 B' } });

    render(<MemoryRouter><LandingApp /></MemoryRouter>);
    fireEvent.pointerMove(screen.getByRole('main'), { pointerType: 'mouse', clientX: 84, clientY: 126 });

    expect(document.querySelectorAll('.gate-particle').length).toBeGreaterThanOrEqual(3);
  });

  it('gives body-level click ripples a concrete border color', () => {
    getHome.mockResolvedValue({ recent_projects: [], preview_pool: [], popular_tags: [], stats: { total_projects: 0, total_size: 0, total_size_fmt: '0 B' } });

    render(<MemoryRouter><LandingApp /></MemoryRouter>);
    fireEvent.pointerDown(screen.getByRole('main'), { pointerType: 'mouse', clientX: 84, clientY: 126 });

    expect(document.querySelector<HTMLElement>('.gate-ripple')?.style.borderColor).toBe('rgb(99, 102, 241)');
  });
});
