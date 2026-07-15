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

  it.each([
    ['language', 'header.language', 'English'],
    ['user', 'alice', 'header.logout'],
  ])('closes the %s menu on Escape from an item and restores trigger focus', (_menu, triggerName, itemName) => {
    render(<Header onSidebarToggle={() => {}} onInfoToggle={() => {}} sidebarOpen={false} infoOpen={false} />);

    const trigger = screen.getByRole('button', { name: triggerName });
    fireEvent.click(trigger);
    const item = screen.getByRole('button', { name: itemName });
    item.focus();

    fireEvent.keyDown(item, { key: 'Escape' });

    expect(trigger.getAttribute('aria-expanded')).toBe('false');
    expect(item.closest('[data-header-menu]')?.hasAttribute('hidden')).toBe(true);
    expect(document.activeElement).toBe(trigger);
  });

  it.each([
    ['header.language', 'English'],
    ['alice', 'header.logout'],
  ])('reactivating %s closes its menu while focus remains within the disclosure', (triggerName, itemName) => {
    render(<Header onSidebarToggle={() => {}} onInfoToggle={() => {}} sidebarOpen={false} infoOpen={false} />);

    const trigger = screen.getByRole('button', { name: triggerName });
    fireEvent.click(trigger);
    const item = screen.getByRole('button', { name: itemName });
    item.focus();
    trigger.focus();
    fireEvent.click(trigger);

    expect(trigger.getAttribute('aria-expanded')).toBe('false');
    expect(item.closest('[data-header-menu]')?.hasAttribute('hidden')).toBe(true);
  });
});
