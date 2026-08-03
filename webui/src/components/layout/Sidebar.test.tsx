// @vitest-environment jsdom
import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import userEvent from '@testing-library/user-event';
import { Sidebar } from './Sidebar';
import { setLang } from '../../i18n';

let api: object = {};
const getTree = vi.fn();
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

vi.mock('../../hooks/useAuth', () => ({
  useAuth: () => ({ api }),
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
    getTree.mockReset();
    api = {};
    useInvalidationMock.mockReset();
  });

  it('registers only the tree projection domain', async () => {
    await renderTree();
    expect(useInvalidationMock.mock.calls[0]?.[0]).toEqual(['tree']);
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
});
