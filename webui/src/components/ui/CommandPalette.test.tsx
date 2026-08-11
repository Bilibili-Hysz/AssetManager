// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { CommandPalette } from './CommandPalette';

const searchState = {
  query: '',
  results: [] as Array<{ name: string; path: string; type: string; extension: string; category: string }>,
  isSearching: false,
  setQuery: vi.fn(),
  clear: vi.fn(),
};

vi.mock('../../hooks/useSearch', () => ({ useSearch: () => searchState }));
vi.mock('../../hooks/useI18n', () => ({
  useI18n: () => ({
    t: (key: string, ...args: Array<string | number>) => {
      const values: Record<string, string> = {
        'commands.title': 'Command palette',
        'commands.placeholder': 'Search...',
        'commands.empty_title': 'Type to search',
        'commands.empty_hint': 'Search by path',
        'commands.mode_gallery': 'Gallery',
        'commands.mode_workspace': 'Workspace',
        'commands.navigate': 'Navigate',
        'commands.open': 'Open',
        'commands.close': 'Close',
        'action.close': 'Close',
        'commands.folder': 'Folder',
        'commands.file': 'File',
      };
      if (key === 'commands.no_results') return 'No results for ' + String(args[0]);
      return values[key] ?? key;
    },
  }),
}));

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{location.pathname}{location.search}</output>;
}

describe('CommandPalette', () => {
  beforeAll(() => {
    HTMLElement.prototype.scrollIntoView = vi.fn();
  });

  beforeEach(() => {
    searchState.query = '';
    searchState.results = [];
    searchState.isSearching = false;
    searchState.setQuery.mockReset();
    searchState.clear.mockReset();
  });

  afterEach(cleanup);

  it('renders an accessible empty state and sends input to the shared search hook', () => {
    render(<MemoryRouter><CommandPalette open={true} onClose={vi.fn()} /></MemoryRouter>);
    expect(screen.getByRole('dialog', { name: 'Command palette' })).toBeDefined();
    expect(screen.getByText('Type to search')).toBeDefined();
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'folder' } });
    expect(searchState.setQuery).toHaveBeenCalledWith('folder');
  });

  it('opens a selected Gallery result with the current path contract', () => {
    searchState.query = 'folder';
    searchState.results = [{ name: 'Folder', path: 'folder', type: 'dir', extension: '', category: 'directory' }];
    const onClose = vi.fn();
    render(<MemoryRouter initialEntries={['/gallery']}><CommandPalette open={true} onClose={onClose} /><LocationProbe /></MemoryRouter>);
    fireEvent.click(screen.getByTestId('command-result-0'));
    expect(onClose).toHaveBeenCalledOnce();
    expect(screen.getByTestId('location').textContent).toBe('/gallery/collection?path=folder');
  });

  it('uses ArrowDown and Enter to open the second Workspace result', () => {
    searchState.query = 'asset';
    searchState.results = [
      { name: 'one.png', path: 'one.png', type: 'file', extension: '.png', category: 'image' },
      { name: 'two.png', path: 'nested/two.png', type: 'file', extension: '.png', category: 'image' },
    ];
    const onClose = vi.fn();
    render(<MemoryRouter initialEntries={['/browse']}><CommandPalette open={true} onClose={onClose} /><LocationProbe /></MemoryRouter>);
    const dialog = screen.getByRole('dialog', { name: 'Command palette' });
    fireEvent.keyDown(dialog, { key: 'ArrowDown' });
    fireEvent.keyDown(dialog, { key: 'Enter' });
    expect(screen.getByTestId('location').textContent).toBe('/detail?path=nested%2Ftwo.png&from=workspace&context=nested');
  });
});
