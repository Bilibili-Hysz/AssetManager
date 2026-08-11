// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import DetailPage from './DetailPage';

const { getProjectDetail, saveNotes, useInvalidationMock, authApi, showToast } = vi.hoisted(() => ({
  getProjectDetail: vi.fn(),
  saveNotes: vi.fn(),
  useInvalidationMock: vi.fn(),
  authApi: { buildUrl: (path: string) => `/api/${path}` },
  showToast: vi.fn(),
}));
const authState = { identityGeneration: 0, capabilities: { settings: true, manage_links: true } };

vi.mock('../hooks/useAuth', () => ({
  useAuth: () => ({ api: authApi, identityGeneration: authState.identityGeneration, capabilities: authState.capabilities }),
}));
vi.mock('../api/metadata', () => ({
  createMetadataApi: () => ({ getProjectDetail }),
}));
vi.mock('../api/notes', () => ({
  createNotesApi: () => ({ save: saveNotes }),
}));
vi.mock('../hooks/useInvalidation', () => ({
  useInvalidation: useInvalidationMock,
}));
vi.mock('../components/ui/Toast', () => ({
  useToast: () => ({ showToast }),
}));
vi.mock('../hooks/useI18n', () => ({
  useI18n: () => ({ t: (key: string) => key }),
}));
vi.mock('../hooks/useQuota', () => ({
  useQuota: () => ({ guardDownload: async () => true, refresh: vi.fn(), quota: null }),
}));
vi.mock('../components/ui/Skeleton', () => ({ Skeleton: () => <div data-testid="skeleton" /> }));
vi.mock('../components/viewer/ImageViewer', () => ({ ImageViewer: () => null }));

function Location() {
  const location = useLocation();
  return <output data-testid="location">{location.pathname}{location.search}</output>;
}

const detail = {
  path: 'folder/Project',
  name: 'Project',
  file_count: 2,
  total_size_fmt: '2 KB',
  modified: 0,
  thumbnail_url: '/thumbnail.jpg',
  tags: ['featured'],
  notes: 'Project notes',
  urls: ['https://example.com/project'],
  images: [{ name: 'cover.png', thumb_url: '/cover-thumb.jpg', url: '/cover.jpg' }],
  files: [{ name: 'cover.png', size_fmt: '2 KB' }],
  download_url: '/api/download/folder%2FProject',
};

describe('DetailPage', () => {
  beforeEach(() => {
    getProjectDetail.mockReset();
    getProjectDetail.mockResolvedValue(detail);
    saveNotes.mockReset();
    saveNotes.mockResolvedValue({ ok: true, path: detail.path, notes: 'Updated notes' });
    showToast.mockReset();
    useInvalidationMock.mockReset();
    authState.identityGeneration = 0;
    authState.capabilities = { settings: true, manage_links: true };
  });

  afterEach(() => cleanup());

  it('registers the detail projection domains', async () => {
    render(<MemoryRouter initialEntries={['/detail?path=folder%2FProject']}><DetailPage /></MemoryRouter>);
    await waitFor(() => expect(useInvalidationMock.mock.calls[0]?.[0]).toEqual(['project_detail', 'metadata', 'tags']));
  });

  it('does not restore detail data from the previous identity generation', async () => {
    let resolveStale!: (value: typeof detail) => void;
    let resolveCurrent!: (value: typeof detail) => void;
    const stale = new Promise<typeof detail>(resolve => { resolveStale = resolve; });
    const current = new Promise<typeof detail>(resolve => { resolveCurrent = resolve; });
    getProjectDetail.mockReset();
    getProjectDetail.mockReturnValueOnce(stale).mockReturnValueOnce(current);

    const { rerender } = render(<MemoryRouter initialEntries={['/detail?path=folder%2FProject']}><DetailPage /></MemoryRouter>);
    await waitFor(() => expect(getProjectDetail).toHaveBeenCalledTimes(1));

    authState.identityGeneration = 1;
    rerender(<MemoryRouter initialEntries={['/detail?path=folder%2FProject']}><DetailPage /></MemoryRouter>);
    await waitFor(() => expect(getProjectDetail).toHaveBeenCalledTimes(2));

    resolveStale(detail);
    await Promise.resolve();
    expect(screen.queryByRole('heading', { name: 'Project' })).toBeNull();

    resolveCurrent(detail);
    await screen.findByRole('heading', { name: 'Project' });
  });

  it('decodes the project path before loading detail data and renders its sections', async () => {
    render(
      <MemoryRouter initialEntries={['/detail?path=folder%2FProject']}>
        <DetailPage />
      </MemoryRouter>,
    );

    await waitFor(() => expect(getProjectDetail).toHaveBeenCalledWith('folder/Project', expect.any(AbortSignal)));
    await screen.findByRole('heading', { name: 'Project' });
    expect(screen.getByRole('heading', { name: 'Project' })).toBeDefined();
    expect(screen.getByText('detail.images')).toBeDefined();
    expect(screen.getByText('detail.files (2)')).toBeDefined();
    expect(screen.getByRole('link', { name: 'detail.download_all' }).getAttribute('href')).toBe(detail.download_url);
  });

  it('uses browser history for Back so the original browse query is restored', async () => {
    render(
      <MemoryRouter initialEntries={['/browse?path=folder%2FProject', '/detail?path=folder%2FProject']} initialIndex={1}>
        <Routes>
          <Route path="/browse" element={<Location />} />
          <Route path="/detail" element={<DetailPage />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => expect(getProjectDetail).toHaveBeenCalledWith('folder/Project', expect.any(AbortSignal)));
    fireEvent.click(screen.getByRole('button', { name: 'detail.back' }));
    expect(screen.getByTestId('location').textContent).toBe('/browse?path=folder%2FProject');
  });
  it('saves edited notes through the API and updates the rendered detail', async () => {
    render(<MemoryRouter initialEntries={['/detail?path=folder%2FProject']}><DetailPage /></MemoryRouter>);
    await screen.findByRole('heading', { name: 'Project' });

    fireEvent.click(screen.getByRole('button', { name: 'info.edit_notes' }));
    const editor = screen.getByRole('textbox', { name: 'info.notes' });
    fireEvent.change(editor, { target: { value: 'Updated notes' } });
    fireEvent.click(screen.getByRole('button', { name: 'info.save_notes' }));

    await waitFor(() => expect(saveNotes).toHaveBeenCalledWith('folder/Project', 'Updated notes'));
    expect(await screen.findByText('Updated notes')).toBeDefined();
    expect(showToast).toHaveBeenCalledWith('info.notes_saved', 'success');
  });

});
