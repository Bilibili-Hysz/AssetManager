// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AppHeader } from './AppHeader';

const logout = vi.fn();
const navigateMock = vi.fn();

vi.mock('react-router-dom', async importOriginal => {
  const actual = await importOriginal<typeof import('react-router-dom')>();
  return { ...actual, useNavigate: () => navigateMock };
});
vi.mock('../../hooks/useAuth', () => ({
  useAuth: () => ({
    user: { username: 'alice' },
    role: 'admin',
    logout,
    serverInfo: { share_name: 'Assets' },
  }),
}));
vi.mock('../../hooks/useI18n', () => ({
  useI18n: () => ({
    t: (key: string) => ({
      'gallery.open_home': 'Open gallery home',
      'gallery.nav_home': 'Gallery',
      'gallery.workspace': 'Workspace',
      'header.primary_navigation': 'Primary navigation',
      'header.search': 'Search',
      'header.search_shortcut': 'Ctrl K',
      'header.no_results': 'No results',
      'header.language': 'Language',
      'gallery.theme_light': 'Light theme',
      'gallery.theme_dark': 'Dark theme',
      'perm.admin': 'Admin',
      'perm.user': 'User',
      'header.admin': 'Admin',
      'header.logout': 'Logout',
    }[key] ?? key),
    lang: 'en',
    setLang: vi.fn(),
    supportedLangs: ['en', 'zh', 'ja'],
  }),
}));
vi.mock('../../hooks/useTheme', () => ({ useTheme: () => ({ theme: 'dark', toggleTheme: vi.fn() }) }));
vi.mock('../../hooks/useSearch', () => ({
  useSearch: () => ({ query: '', results: [], isSearching: false, setQuery: vi.fn(), clear: vi.fn() }),
}));

afterEach(() => {
  cleanup();
  logout.mockReset();
});

describe('AppHeader', () => {
  it('keeps the migrated logout action discoverable as a native button', () => {
    render(<MemoryRouter><AppHeader /></MemoryRouter>);

    fireEvent.click(screen.getByRole('button', { name: 'alice' }));
    const logoutButton = screen.getByRole('button', { name: 'Logout' });
    fireEvent.click(logoutButton);

    expect(logout).toHaveBeenCalledOnce();
  });
});

describe('AppHeader admin navigation', () => {
  it('navigates to /admin when an admin clicks the Admin item', () => {
    render(<MemoryRouter><AppHeader /></MemoryRouter>);
    fireEvent.click(screen.getByRole('button', { name: 'alice' }));
    fireEvent.click(screen.getByRole('button', { name: 'Admin' }));
    expect(navigateMock).toHaveBeenCalledWith('/admin');
  });

});
