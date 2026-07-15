// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Header } from './Header';

let testLang = 'en';
const emptySearchMessages: Record<string, string> = { en: 'No results', zh: '无结果', ja: '結果がありません' };

vi.mock('../../hooks/useAuth', () => ({
  useAuth: () => ({ user: { username: 'alice' }, role: 'user', logout: vi.fn(), serverInfo: null }),
}));
vi.mock('../../hooks/useI18n', () => ({
  useI18n: () => ({ t: (key: string) => key === 'header.no_results' ? emptySearchMessages[testLang] : key, lang: testLang, setLang: vi.fn(), supportedLangs: ['en', 'zh', 'ja'] }),
}));
vi.mock('../../hooks/useTheme', () => ({ useTheme: () => ({ theme: 'dark', toggleTheme: vi.fn() }) }));
vi.mock('../../hooks/useSearch', () => ({
  useSearch: () => {
    const [query, setQuery] = useState('');
    return { query, results: [], isSearching: false, setQuery, clear: () => setQuery('') };
  },
}));
vi.mock('react-router-dom', () => ({ Link: ({ children }: { children: React.ReactNode }) => <a href="/">{children}</a>, useNavigate: () => vi.fn() }));

describe('Header menus', () => {
  afterEach(cleanup);

  it.each([
    ['en', 'No results'],
    ['zh', '无结果'],
    ['ja', '結果がありません'],
  ])('renders localized empty search state in %s', (lang, message) => {
    testLang = lang;
    render(<Header onSidebarToggle={() => {}} onInfoToggle={() => {}} sidebarOpen={false} infoOpen={false} />);
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'missing' } });
    expect(screen.getByText(message)).toBeDefined();
  });

  it.each(['header.language', 'alice'])('toggles %s once per native Enter and Space activation', async triggerName => {
    const user = userEvent.setup();
    render(<Header onSidebarToggle={() => {}} onInfoToggle={() => {}} sidebarOpen={false} infoOpen={false} />);

    const trigger = screen.getByRole('button', { name: triggerName });
    const clickListener = vi.fn();
    trigger.addEventListener('click', clickListener);
    trigger.focus();

    await user.keyboard('{Enter}');
    expect(trigger.getAttribute('aria-expanded')).toBe('true');
    expect(clickListener).toHaveBeenCalledTimes(1);
    await user.keyboard('{Enter}');
    expect(trigger.getAttribute('aria-expanded')).toBe('false');
    expect(clickListener).toHaveBeenCalledTimes(2);

    await user.keyboard(' ');
    expect(trigger.getAttribute('aria-expanded')).toBe('true');
    expect(clickListener).toHaveBeenCalledTimes(3);
    await user.keyboard(' ');
    expect(trigger.getAttribute('aria-expanded')).toBe('false');
    expect(clickListener).toHaveBeenCalledTimes(4);
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
