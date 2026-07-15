// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Header } from './Header';

vi.mock('../../hooks/useAuth', () => ({
  useAuth: () => ({ user: { username: 'alice' }, role: 'user', logout: vi.fn(), serverInfo: null }),
}));
vi.mock('../../hooks/useI18n', () => ({
  useI18n: () => ({ t: (key: string) => key, lang: 'en', setLang: vi.fn(), supportedLangs: ['en', 'zh'] }),
}));
vi.mock('../../hooks/useTheme', () => ({ useTheme: () => ({ theme: 'dark', toggleTheme: vi.fn() }) }));
vi.mock('../../hooks/useSearch', () => ({
  useSearch: () => ({ query: '', results: [], isSearching: false, setQuery: vi.fn(), clear: vi.fn() }),
}));
vi.mock('react-router-dom', () => ({ Link: ({ children }: { children: React.ReactNode }) => <a href="/">{children}</a>, useNavigate: () => vi.fn() }));

describe('Header menus', () => {
  afterEach(cleanup);

  it('opens the user menu from the labelled button with keyboard focus and click', () => {
    render(<Header onSidebarToggle={() => {}} onInfoToggle={() => {}} sidebarOpen={false} infoOpen={false} />);

    const userButton = screen.getByRole('button', { name: 'alice' });
    fireEvent.keyDown(userButton, { key: 'Enter' });
    expect(userButton.getAttribute('aria-expanded')).toBe('true');
    expect(screen.getByRole('button', { name: 'header.logout' })).toBeDefined();
    fireEvent.click(userButton);
    expect(userButton.getAttribute('aria-expanded')).toBe('false');
  });
});
