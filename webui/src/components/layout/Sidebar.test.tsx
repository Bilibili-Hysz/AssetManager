// @vitest-environment jsdom
import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import userEvent from '@testing-library/user-event';
import { Sidebar } from './Sidebar';
import { setLang } from '../../i18n';

let api: object = {};
let identityGeneration = 0;
const getTree = vi.fn();
const listTags = vi.fn();
const navigateMock = vi.fn();
let favoriteItems: Array<{ name: string; path: string; kind: 'collection' | 'project' | 'artwork'; parent_path: string | null; modified: number }> = [];
const { useInvalidationMock } = vi.hoisted(() => ({ useInvalidationMock: vi.fn() }));

const tree = [
  {
    name: 'Workspace', path: 'workspace', type: 'dir' as const, is_leaf: false,
    children: [
      {
        name: 'Assets', path: 'workspace/assets', type: 'dir' as const, is_leaf: false,
        children: [
          { name: 'logo.svg', path: 'workspace/assets/logo.svg', type: 'file' as const, is_leaf: true },
        ],
      },
      { name: 'README.md', path: 'workspace/README.md', type: 'file' as const, is_leaf: true },
    ],
  },
];

async function renderTree(currentPath = '') {
  getTree.mockResolvedValue({ tree });
  const onNavigate = vi.fn();
  render(<Sidebar onNavigate={onNavigate} currentPath={currentPath} />, { wrapper: MemoryRouter });
  await screen.findByText('Workspace');
  return { onNavigate };
}

vi.mock('react-router-dom', async importOriginal => ({
  ...(await importOriginal<typeof import('react-router-dom')>()),
  useNavigate: () => navigateMock,
}));

vi.mock('../../hooks/useFavorites', () => ({
  useFavorites: () => ({ items: favoriteItems, loading: false }),
}));

vi.mock('../../api/tags', () => ({
  createTagsApi: () => ({ list: listTags }),
}));

const listCollections = vi.fn();
const createCollection = vi.fn();
const deleteCollection = vi.fn();
const listMembers = vi.fn();
const evaluateCollection = vi.fn();
vi.mock('../../api/collections', () => ({
  createCollectionsApi: () => ({
    list: listCollections,
    create: createCollection,
    delete: deleteCollection,
    members: listMembers,
    evaluate: evaluateCollection,
    update: vi.fn(),
    addMembers: vi.fn(),
    removeMembers: vi.fn(),
  }),
}));

vi.mock('../../hooks/useAuth', () => ({
  useAuth: () => ({ api, identityGeneration }),
}));

vi.mock('../../api/metadata', () => ({
  createMetadataApi: () => ({ getTree }),
}));
vi.mock('../../hooks/useInvalidation', () => ({
  useInvalidation: useInvalidationMock,
}));

describe('Sidebar', () => {
  afterEach(cleanup);

  beforeEach(() => {
    setLang('en');
    getTree.mockReset().mockResolvedValue({ tree });
    listTags.mockReset().mockResolvedValue({ tags: [] });
    listCollections.mockReset().mockResolvedValue({ collections: [] });
    createCollection.mockReset().mockResolvedValue({ collection: { id: 1 } });
    deleteCollection.mockReset().mockResolvedValue({ ok: true });
    listMembers.mockReset().mockResolvedValue({ members: [] });
    evaluateCollection.mockReset().mockResolvedValue({ results: [] });
    navigateMock.mockReset();
    favoriteItems = [];
    api = {};
    identityGeneration = 0;
    useInvalidationMock.mockReset();
  });

  it('registers only the tree projection domain', async () => {
    await renderTree();
    expect(useInvalidationMock.mock.calls.map(call => call[0])).toEqual(expect.arrayContaining([['tree'], ['tags']]));
  });

  it('uses translated folder controls after switching to Chinese', async () => {
    setLang('zh');
    await renderTree();

    expect(screen.getByRole('heading', { name: '文件夹' })).toBeDefined();
    expect(screen.getByRole('button', { name: '全部展开' })).toBeDefined();
    expect(screen.getByRole('button', { name: '全部折叠' })).toBeDefined();
  });

  it('expands all nested directories and collapses them again', async () => {
    const user = userEvent.setup();
    await renderTree();

    expect(screen.getByRole('button', { name: /expand all/i }).className).toContain('h-10');
    expect(screen.getByRole('button', { name: /expand all/i }).className).toContain('w-10');
    expect(screen.getByRole('button', { name: /collapse all/i }).className).toContain('h-10');
    expect(screen.getByRole('button', { name: /collapse all/i }).className).toContain('w-10');

    expect(screen.queryByText('Assets')).toBeNull();
    await user.click(screen.getByRole('button', { name: /expand all/i }));
    expect(screen.getByText('Assets')).toBeDefined();
    expect(screen.getByText('logo.svg')).toBeDefined();

    await user.click(screen.getByRole('button', { name: /collapse all/i }));
    expect(screen.queryByText('Assets')).toBeNull();
  });

  it('expands every ancestor of the active path', async () => {
    await renderTree('workspace/assets/logo.svg');

    // Active-ancestor expansion runs in a follow-up effect after the tree
    // loads, so wait for it instead of asserting synchronously.
    await screen.findByText('Assets');
    expect(screen.getByText('logo.svg')).toBeDefined();
  });

  it('clears every expanded path when collapsing all, including active ancestors', async () => {
    const user = userEvent.setup();
    await renderTree('workspace/assets/logo.svg');

    await screen.findByText('Assets');
    await user.click(screen.getByRole('button', { name: /collapse all/i }));

    expect(screen.queryByText('Assets')).toBeNull();
  });

  it('navigates directory rows but chevrons only change expansion', async () => {
    const user = userEvent.setup();
    const { onNavigate } = await renderTree();

    await user.click(screen.getByRole('button', { name: /expand workspace/i }));
    expect(onNavigate).not.toHaveBeenCalled();
    expect(screen.getByText('Assets')).toBeDefined();

    await user.click(screen.getByTestId('tree-node-icon-workspace'));
    expect(onNavigate).toHaveBeenCalledTimes(1);
    expect(onNavigate).toHaveBeenCalledWith('workspace');
  });

  it('navigates from a nested directory indentation while its chevron only toggles', async () => {
    const user = userEvent.setup();
    const { onNavigate } = await renderTree();

    await user.click(screen.getByRole('button', { name: /expand workspace/i }));
    const assetsChevron = screen.getByRole('button', { name: /expand assets/i });

    await user.click(assetsChevron);
    expect(onNavigate).not.toHaveBeenCalled();
    expect(screen.getByText('logo.svg')).toBeDefined();

    await user.click(screen.getByTestId('tree-node-indent-workspace/assets'));
    expect(onNavigate).toHaveBeenCalledTimes(1);
    expect(onNavigate).toHaveBeenCalledWith('workspace/assets');
  });

  it('uses localized tree expansion labels and filter-disabled titles while retaining manual expansion', async () => {
    const user = userEvent.setup();
    setLang('zh');
    await renderTree();

    await user.click(screen.getByRole('button', { name: '展开 Workspace' }));
    expect(screen.getByText('Assets')).toBeDefined();

    const input = screen.getByRole('textbox', { name: '筛选目录...' });
    await user.type(input, 'logo');
    expect(screen.getByText('Workspace')).toBeDefined();
    expect(screen.getByText('Assets')).toBeDefined();
    expect(screen.getByText('logo.svg')).toBeDefined();

    const expandAll = screen.getByRole('button', { name: '全部展开' });
    const collapseAll = screen.getByRole('button', { name: '全部折叠' });
    expect((expandAll as HTMLButtonElement).disabled).toBe(true);
    expect((collapseAll as HTMLButtonElement).disabled).toBe(true);
    expect(expandAll.getAttribute('aria-disabled')).toBe('true');
    expect(collapseAll.getAttribute('title')).toBe('清除搜索筛选条件以更改手动展开状态');
    await user.click(expandAll);
    await user.click(collapseAll);

    const collapseWorkspace = screen.getByRole('button', { name: '折叠 Workspace' });
    expect((collapseWorkspace as HTMLButtonElement).disabled).toBe(true);
    expect(collapseWorkspace.getAttribute('aria-disabled')).toBe('true');
    expect(collapseWorkspace.getAttribute('title')).toBe('清除搜索筛选条件以更改手动展开状态');
    await user.click(collapseWorkspace);

    await user.clear(input);
    expect(screen.getByText('Assets')).toBeDefined();
    expect(screen.queryByText('logo.svg')).toBeNull();
  });

  it('ignores a response from a superseded tree request', async () => {
    let resolveFirst!: (value: { tree: Array<{ name: string; path: string; is_leaf: boolean }> }) => void;
    let resolveSecond!: (value: { tree: Array<{ name: string; path: string; is_leaf: boolean }> }) => void;
    getTree
      .mockImplementationOnce(() => new Promise(resolve => { resolveFirst = resolve; }))
      .mockImplementationOnce(() => new Promise(resolve => { resolveSecond = resolve; }));

    render(<Sidebar onNavigate={() => {}} currentPath="" />, { wrapper: MemoryRouter });
    await act(async () => {
      useInvalidationMock.mock.calls[0]![1]!();
    });

    await act(async () => {
      resolveSecond({ tree: [{ name: 'Current', path: 'current', is_leaf: false }] });
    });
    expect(screen.getByText('Current')).toBeDefined();

    await act(async () => {
      resolveFirst({ tree: [{ name: 'Stale', path: 'stale', is_leaf: false }] });
    });
    expect(screen.queryByText('Stale')).toBeNull();
    expect(screen.getByText('Current')).toBeDefined();
  });

  it('loads, filters, highlights, and clears real tags', async () => {
    const user = userEvent.setup();
    listTags.mockResolvedValue({ tags: [
      { id: 1, name: 'branding', count: 4 },
      { id: 2, name: 'icons', count: 2 },
    ] });
    const onTagFilter = vi.fn();
    const onClearTagFilter = vi.fn();
    render(<Sidebar onNavigate={() => {}} currentPath="" activeTag="branding" onTagFilter={onTagFilter} onClearTagFilter={onClearTagFilter} />, { wrapper: MemoryRouter });

    expect((await screen.findByRole('button', { name: /branding/ })).getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByText('4')).toBeDefined();
    await user.click(screen.getByRole('button', { name: /branding/ }));
    expect(onClearTagFilter).toHaveBeenCalledTimes(1);

    const search = screen.getByRole('textbox', { name: 'Tags' });
    await user.type(search, 'icon');
    expect(screen.getByRole('button', { name: /icons/ })).toBeDefined();
    expect(screen.queryByRole('button', { name: 'branding' })).toBeNull();
    await user.click(screen.getByRole('button', { name: /icons/ }));
    expect(onTagFilter).toHaveBeenCalledWith('icons');
  });

  it('renders favorites and navigates them with workspace context', async () => {
    favoriteItems = [{ name: 'Logo', path: 'workspace/assets/logo.svg', kind: 'artwork', parent_path: 'workspace/assets', modified: 1 }];
    render(<Sidebar onNavigate={() => {}} currentPath="" />, { wrapper: MemoryRouter });

    const favorite = await screen.findByRole('button', { name: 'Open Logo' });
    await userEvent.click(favorite);
    expect(navigateMock).toHaveBeenCalledWith('/detail?path=workspace%2Fassets%2Flogo.svg&from=workspace&context=workspace%2Fassets');
  });

  it('renders the collections group and expands manual members on click', async () => {
    const user = userEvent.setup();
    listCollections.mockResolvedValue({ collections: [
      { id: 7, name: 'hero shots', kind: 'manual', query: {}, member_count: 2, created_at: 1, updated_at: 1 },
      { id: 8, name: 'big pngs', kind: 'smart', query: { extensions: ['.png'] }, member_count: 0, created_at: 1, updated_at: 1 },
    ] });
    listMembers.mockResolvedValue({ members: [
      { path: 'workspace/assets/logo.svg', added_at: 1, exists: true },
      { path: 'workspace/gone.svg', added_at: 2, exists: false },
    ] });
    render(<Sidebar onNavigate={() => {}} currentPath="" />, { wrapper: MemoryRouter });

    expect(await screen.findByRole('heading', { name: 'Collections' })).toBeDefined();
    await user.click(await screen.findByRole('button', { name: /^hero shots/ }));
    expect(listMembers).toHaveBeenCalledWith(7);
    expect(await screen.findByText('logo.svg')).toBeDefined();
    // Members navigate through the workspace detail route.
    await user.click(screen.getByRole('button', { name: 'Open logo.svg' }));
    expect(navigateMock).toHaveBeenCalledWith(
      '/detail?path=workspace%2Fassets%2Flogo.svg&from=workspace&context=workspace%2Fassets',
    );
    // Missing member paths stay visible but are marked absent.
    expect(screen.getByText('gone.svg').closest('button')?.className).toContain('line-through');
  });

  it('expands a smart collection through the evaluate endpoint', async () => {
    const user = userEvent.setup();
    listCollections.mockResolvedValue({ collections: [
      { id: 8, name: 'big pngs', kind: 'smart', query: { extensions: ['.png'] }, member_count: 0, created_at: 1, updated_at: 1 },
    ] });
    evaluateCollection.mockResolvedValue({ results: [
      { path: 'workspace/assets/logo.svg', name: 'logo.svg', extension: '.svg', size: 1, mtime: 1 },
    ] });
    render(<Sidebar onNavigate={() => {}} currentPath="" />, { wrapper: MemoryRouter });

    await user.click(await screen.findByRole('button', { name: /^big pngs/ }));
    // The mocked factory endpoint receives the id; default paging is the
    // factory's concern (see collections.contract.test.ts).
    expect(evaluateCollection).toHaveBeenCalledWith(8);
    expect(await screen.findByText('logo.svg')).toBeDefined();
  });

  it('refreshes expanded collection members after a collections invalidation', async () => {
    const user = userEvent.setup();
    const collection = { id: 7, name: 'hero shots', kind: 'manual' as const, query: {}, member_count: 1, created_at: 1, updated_at: 1 };
    listCollections.mockResolvedValue({ collections: [collection] });
    listMembers
      .mockResolvedValueOnce({ members: [{ path: 'workspace/old.svg', added_at: 1, exists: true }] })
      .mockResolvedValueOnce({ members: [{ path: 'workspace/current.svg', added_at: 2, exists: true }] });
    render(<Sidebar onNavigate={() => {}} currentPath="" />, { wrapper: MemoryRouter });

    await user.click(await screen.findByRole('button', { name: /^hero shots/ }));
    expect(await screen.findByText('old.svg')).toBeDefined();

    await act(async () => {
      useInvalidationMock.mock.calls.find(call => call[0][0] === 'collections')![1]!();
    });

    expect(await screen.findByText('current.svg')).toBeDefined();
    expect(screen.queryByText('old.svg')).toBeNull();
    expect(listMembers).toHaveBeenCalledTimes(2);
  });

  it('does not let a superseded collection member response replace refreshed members', async () => {
    const user = userEvent.setup();
    const collection = { id: 7, name: 'hero shots', kind: 'manual' as const, query: {}, member_count: 1, created_at: 1, updated_at: 1 };
    let resolveFirst!: (value: { members: Array<{ path: string; added_at: number; exists: boolean }> }) => void;
    let resolveSecond!: (value: { members: Array<{ path: string; added_at: number; exists: boolean }> }) => void;
    listCollections.mockResolvedValue({ collections: [collection] });
    listMembers
      .mockImplementationOnce(() => new Promise(resolve => { resolveFirst = resolve; }))
      .mockImplementationOnce(() => new Promise(resolve => { resolveSecond = resolve; }));
    render(<Sidebar onNavigate={() => {}} currentPath="" />, { wrapper: MemoryRouter });

    await user.click(await screen.findByRole('button', { name: /^hero shots/ }));
    await act(async () => {
      useInvalidationMock.mock.calls.find(call => call[0][0] === 'collections')![1]!();
    });
    await waitFor(() => expect(listMembers).toHaveBeenCalledTimes(2));

    await act(async () => { resolveSecond({ members: [{ path: 'workspace/current.svg', added_at: 2, exists: true }] }); });
    expect(await screen.findByText('current.svg')).toBeDefined();
    await act(async () => { resolveFirst({ members: [{ path: 'workspace/stale.svg', added_at: 1, exists: true }] }); });

    expect(screen.queryByText('stale.svg')).toBeNull();
    expect(screen.getByText('current.svg')).toBeDefined();
  });

  it('drops pending collection members when the authenticated identity changes', async () => {
    const user = userEvent.setup();
    const collection = { id: 7, name: 'hero shots', kind: 'manual' as const, query: {}, member_count: 1, created_at: 1, updated_at: 1 };
    let resolveFirst!: (value: { members: Array<{ path: string; added_at: number; exists: boolean }> }) => void;
    let resolveSecond!: (value: { members: Array<{ path: string; added_at: number; exists: boolean }> }) => void;
    listCollections.mockResolvedValue({ collections: [collection] });
    listMembers
      .mockImplementationOnce(() => new Promise(resolve => { resolveFirst = resolve; }))
      .mockImplementationOnce(() => new Promise(resolve => { resolveSecond = resolve; }));
    const view = render(<Sidebar onNavigate={() => {}} currentPath="" />, { wrapper: MemoryRouter });

    await user.click(await screen.findByRole('button', { name: /^hero shots/ }));
    identityGeneration = 1;
    api = { identity: 'next' };
    view.rerender(<Sidebar onNavigate={() => {}} currentPath="" />);
    await waitFor(() => expect(listMembers).toHaveBeenCalledTimes(2));

    await act(async () => { resolveFirst({ members: [{ path: 'workspace/old-user.svg', added_at: 1, exists: true }] }); });
    expect(screen.queryByText('old-user.svg')).toBeNull();
    await act(async () => { resolveSecond({ members: [{ path: 'workspace/new-user.svg', added_at: 2, exists: true }] }); });
    expect(await screen.findByText('new-user.svg')).toBeDefined();
  });

  it('does not refresh collections when a create response arrives after an identity change', async () => {
    const user = userEvent.setup();
    let resolveCreate!: (value: { collection: { id: number } }) => void;
    createCollection.mockImplementationOnce(() => new Promise(resolve => { resolveCreate = resolve; }));
    const prompt = vi.spyOn(window, 'prompt').mockReturnValue('late collection');
    const view = render(<Sidebar onNavigate={() => {}} currentPath="" />, { wrapper: MemoryRouter });
    await screen.findByRole('heading', { name: 'Collections' });

    await user.click(screen.getByTestId('sidebar-new-collection'));
    identityGeneration = 1;
    api = { identity: 'next' };
    view.rerender(<Sidebar onNavigate={() => {}} currentPath="" />);
    await waitFor(() => expect(listCollections).toHaveBeenCalledTimes(2));
    await act(async () => { resolveCreate({ collection: { id: 9 } }); });

    expect(listCollections).toHaveBeenCalledTimes(2);
    prompt.mockRestore();
  });

  it('does not remove or refresh a collection when a delete response arrives after an identity change', async () => {
    const collection = { id: 7, name: 'hero shots', kind: 'manual' as const, query: {}, member_count: 0, created_at: 1, updated_at: 1 };
    let resolveDelete!: (value: { ok: boolean }) => void;
    listCollections.mockResolvedValue({ collections: [collection] });
    deleteCollection.mockImplementationOnce(() => new Promise(resolve => { resolveDelete = resolve; }));
    const view = render(<Sidebar onNavigate={() => {}} currentPath="" />, { wrapper: MemoryRouter });
    await screen.findByTestId('sidebar-delete-collection-7');

    await userEvent.click(screen.getByTestId('sidebar-delete-collection-7'));
    identityGeneration = 1;
    api = { identity: 'next' };
    view.rerender(<Sidebar onNavigate={() => {}} currentPath="" />);
    await waitFor(() => expect(listCollections).toHaveBeenCalledTimes(2));
    await act(async () => { resolveDelete({ ok: true }); });

    expect(listCollections).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId('sidebar-collection-7')).toBeDefined();
  });

  it('creates a collection through the prompt entry point', async () => {
    const user = userEvent.setup();
    const prompt = vi.spyOn(window, 'prompt').mockReturnValue('new collection');
    render(<Sidebar onNavigate={() => {}} currentPath="" />, { wrapper: MemoryRouter });
    await screen.findByRole('heading', { name: 'Collections' });

    await user.click(screen.getByTestId('sidebar-new-collection'));
    expect(createCollection).toHaveBeenCalledWith('new collection');
    prompt.mockRestore();
  });

  it('shows the live asset_count beside smart collections only', async () => {
    listCollections.mockResolvedValue({ collections: [
      { id: 7, name: 'hero shots', kind: 'manual', query: {}, member_count: 2, created_at: 1, updated_at: 1 },
      { id: 8, name: 'big pngs', kind: 'smart', query: { extensions: ['.png'] }, member_count: 0, created_at: 1, updated_at: 1, asset_count: 12 },
    ] });
    render(<Sidebar onNavigate={() => {}} currentPath="" />, { wrapper: MemoryRouter });

    expect(await screen.findByTestId('sidebar-collection-count-8')).toBeDefined();
    expect(screen.getByTestId('sidebar-collection-count-8').textContent).toBe('12');
    // Manual rows keep their plain member_count, no live count badge.
    expect(screen.queryByTestId('sidebar-collection-count-7')).toBeNull();
    expect(screen.getByTestId('sidebar-collection-7').textContent).toContain('2');
  });

  it('saves the browse-state snapshot as a smart collection query', async () => {
    const user = userEvent.setup();
    const prompt = vi.spyOn(window, 'prompt').mockReturnValue('hero shots');
    const snapshot = { fts: 'hero', tags: ['featured'], tag_match: 'all' };
    render(
      <Sidebar onNavigate={() => {}} currentPath="" collectionSnapshot={snapshot} />,
      { wrapper: MemoryRouter },
    );
    await screen.findByRole('heading', { name: 'Collections' });

    await user.click(screen.getByTestId('sidebar-new-collection'));
    expect(createCollection).toHaveBeenCalledWith('hero shots', 'smart', snapshot);
    prompt.mockRestore();
  });

  it('navigates tree leaves to detail with encoded parent context while directories use onNavigate', async () => {
    const user = userEvent.setup();
    const onNavigate = vi.fn();
    getTree.mockResolvedValue({ tree: [{ name: 'Folder', path: 'workspace/my folder', is_leaf: false, children: [{ name: 'A file', path: 'workspace/my folder/A file.svg', is_leaf: true }] }] });
    render(<Sidebar onNavigate={onNavigate} currentPath="" />, { wrapper: MemoryRouter });
    await user.click(await screen.findByRole('button', { name: 'Folder' }));
    expect(onNavigate).toHaveBeenCalledWith('workspace/my folder');
    await user.click(screen.getByRole('button', { name: 'Expand Folder' }));
    await user.click(screen.getByRole('button', { name: 'A file' }));
    expect(navigateMock).toHaveBeenCalledWith('/detail?path=workspace%2Fmy%20folder%2FA%20file.svg&from=workspace&context=workspace%2Fmy%20folder');
  });

});
