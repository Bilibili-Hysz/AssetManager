// @vitest-environment jsdom
import { act, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';

const TestRouter = ({ children }: { children: React.ReactNode }) => (
  <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
    {children}
  </MemoryRouter>
);
import { Sidebar } from './Sidebar';

let api: object = {};
const getTree = vi.fn();

vi.mock('../../hooks/useAuth', () => ({
  useAuth: () => ({ api }),
}));

vi.mock('../../api/metadata', () => ({
  createMetadataApi: () => ({ getTree }),
}));

describe('Sidebar', () => {
  beforeEach(() => {
    getTree.mockReset();
    api = {};
  });

  it('ignores a response from a superseded tree request', async () => {
    let resolveFirst!: (value: { tree: Array<{ name: string; path: string; is_leaf: boolean }> }) => void;
    let resolveSecond!: (value: { tree: Array<{ name: string; path: string; is_leaf: boolean }> }) => void;
    getTree
      .mockImplementationOnce(() => new Promise(resolve => { resolveFirst = resolve; }))
      .mockImplementationOnce(() => new Promise(resolve => { resolveSecond = resolve; }));

    const view = render(<Sidebar onNavigate={() => {}} currentPath="" />, { wrapper: TestRouter });
    api = {};
    view.rerender(<Sidebar onNavigate={() => {}} currentPath="" />);

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
