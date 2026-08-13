// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, expectTypeOf, it, vi } from 'vitest';
import { Header } from './Header';

let testLang = 'en';
const emptySearchMessages: Record<string, string> = { en: 'No results', zh: '无结果', ja: '結果がありません' };
const toggleMessages: Record<string, Record<string, string>> = {
  en: {
    'action.open_sidebar': 'Open sidebar',
    'action.close_sidebar': 'Close sidebar',
    'mobile.info': 'Open information panel',
    'action.close_info': 'Close information panel',
  },
  zh: {
    'action.open_sidebar': '打开侧栏',
    'action.close_sidebar': '关闭侧栏',
    'mobile.info': '打开信息面板',
    'action.close_info': '关闭信息面板',
  },
  ja: {
    'action.open_sidebar': 'サイドバーを開く',
    'action.close_sidebar': 'サイドバーを閉じる',
    'mobile.info': '情報パネルを開く',
    'action.close_info': '情報パネルを閉じる',
  },
};

vi.mock('../../hooks/useAuth', () => ({
  useAuth: () => ({ user: { username: 'alice' }, role: 'user', logout: vi.fn(), serverInfo: null }),
}));
vi.mock('../../hooks/useI18n', () => ({
  useI18n: () => ({ t: (key: string) => key === 'header.no_results' ? emptySearchMessages[testLang] : toggleMessages[testLang]?.[key] ?? key, lang: testLang, setLang: vi.fn(), supportedLangs: ['en', 'zh', 'ja'] }),
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

  it('does not expose workspace panel controls as public props', () => {
    expectTypeOf(Header).parameters.toEqualTypeOf<[]>();
  });

  it.each([
    ['en', 'No results'],
    ['zh', '无结果'],
    ['ja', '結果がありません'],
  ])('renders localized empty search state in %s', (lang, message) => {
    testLang = lang;
    render(<Header />);
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'missing' } });
    expect(screen.getByText(message)).toBeDefined();
  });

  it('exposes the workspace search by name and does not steal slash from editable elements', () => {
    testLang = 'en';
    render(<Header />);

    const search = screen.getByRole('searchbox', { name: 'header.search' });
    fireEvent.keyDown(document, { key: '/' });
    expect(document.activeElement).toBe(search);

    const textarea = document.createElement('textarea');
    document.body.append(textarea);
    textarea.focus();
    fireEvent.keyDown(textarea, { key: '/' });
    expect(document.activeElement).toBe(textarea);
    textarea.remove();
  });

  it('leaves workspace panel controls to the breadcrumb row', () => {
    testLang = 'en';
    render(<Header />);

    expect(screen.queryByRole('button', { name: 'Open sidebar' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Open information panel' })).toBeNull();
  });

  it.each(['header.language', 'alice'])('toggles %s once per native Enter and Space activation', async triggerName => {
    const user = userEvent.setup();
    render(<Header />);

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
    render(<Header />);

    const trigger = screen.getByRole('button', { name: triggerName });
    fireEvent.click(trigger);
    const item = screen.getByRole('menuitem', { name: itemName });
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
    render(<Header />);

    const trigger = screen.getByRole('button', { name: triggerName });
    fireEvent.click(trigger);
    const item = screen.getByRole('menuitem', { name: itemName });
    item.focus();
    trigger.focus();
    fireEvent.click(trigger);

    expect(trigger.getAttribute('aria-expanded')).toBe('false');
    expect(item.closest('[data-header-menu]')?.hasAttribute('hidden')).toBe(true);
  });
});
