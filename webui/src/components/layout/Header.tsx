import { useRef, useState, useEffect } from 'react';
import { Search, LogOut, Sun, Moon, Globe, User, File, Folder } from 'lucide-react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../../hooks/useAuth';
import { useI18n } from '../../hooks/useI18n';
import { useTheme } from '../../hooks/useTheme';
import { useSearch } from '../../hooks/useSearch';
import type { SearchResult } from '../../types/api';

export function Header() {
  const { user, role, logout, serverInfo } = useAuth();
  const { t, lang, setLang, supportedLangs } = useI18n();
  const { theme, toggleTheme } = useTheme();
  const { query, results, isSearching, setQuery, clear } = useSearch();
  const navigate = useNavigate();
  const searchRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const languageTriggerRef = useRef<HTMLButtonElement>(null);
  const userTriggerRef = useRef<HTMLButtonElement>(null);
  const [showResults, setShowResults] = useState(false);
  const [openMenu, setOpenMenu] = useState<'language' | 'user' | null>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (searchRef.current && !searchRef.current.contains(e.target as Node)) {
        setShowResults(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setOpenMenu(null);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const handleResultClick = (result: SearchResult) => {
    clear();
    setShowResults(false);
    navigate(`/browse?path=${encodeURIComponent(result.path)}`);
  };

  const toggleMenu = (menu: 'language' | 'user') => setOpenMenu(current => current === menu ? null : menu);

  const handleDisclosureKeyDown = (e: React.KeyboardEvent, menu: 'language' | 'user') => {
    if (e.key === 'Escape' && openMenu === menu) {
      e.preventDefault();
      setOpenMenu(null);
      (menu === 'language' ? languageTriggerRef : userTriggerRef).current?.focus();
    }
  };

  // Keyboard shortcut: / to focus search
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      const isEditable = target instanceof HTMLInputElement
        || target instanceof HTMLTextAreaElement
        || target instanceof HTMLSelectElement
        || target?.isContentEditable;
      if (e.key === '/' && !e.ctrlKey && !e.metaKey && !isEditable) {
        e.preventDefault();
        const input = document.querySelector<HTMLInputElement>('#header-search-input');
        input?.focus();
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, []);

  return (
    <header
      className="flex items-center gap-3 px-4 h-14 transition-theme"
      style={{
        borderBottom: '1px solid var(--color-border)',
        backgroundColor: 'var(--color-surface)',
        backdropFilter: 'blur(12px)',
      }}
    >
      {/* Left: brand */}
      <div className="flex items-center gap-2 flex-shrink-0">
        <Link to="/" className="flex items-center gap-2.5">
          <div
            className="w-7 h-7 rounded-md flex items-center justify-center text-sm font-bold text-white"
            style={{ backgroundColor: 'var(--color-accent)' }}
          >
            A
          </div>
          <span className="text-sm font-semibold hidden sm:inline" style={{ color: 'var(--color-text)' }}>
            {serverInfo?.share_name ?? 'AssetManager'}
          </span>
        </Link>
      </div>

      {/* Center: search */}
      <div ref={searchRef} className="flex-1 max-w-md relative">
        <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2" style={{ color: 'var(--color-text-muted)' }} aria-hidden="true" />
        <input
          id="header-search-input"
          type="text"
          role="searchbox"
          aria-label={t('header.search')}
          value={query}
          onChange={e => { setQuery(e.target.value); setShowResults(true); }}
          onFocus={() => { if (results.length > 0) setShowResults(true); }}
          placeholder={`${t('header.search')}...`}
          className="w-full pl-9 pr-4 py-1.5 rounded-lg text-sm transition-colors"
          style={{
            backgroundColor: 'var(--input-bg)',
            border: '1px solid var(--input-border)',
            color: 'var(--color-text)',
          }}
        />
        {/* Search results dropdown */}
        {showResults && (query.trim() || isSearching) && (
          <div
            className="absolute top-full left-0 right-0 mt-1.5 rounded-lg max-h-80 overflow-auto z-50"
            style={{
              backgroundColor: 'var(--color-surface)',
              border: '1px solid var(--color-border)',
              boxShadow: 'var(--shadow-lg)',
            }}
          >
            {isSearching ? (
              <div className="p-3 text-center text-sm" style={{ color: 'var(--color-text-secondary)' }}>{t('browse.loading')}</div>
            ) : results.length === 0 ? (
              <div className="p-3 text-center text-sm" style={{ color: 'var(--color-text-secondary)' }}>{t('header.no_results')}</div>
            ) : (
              results.map(result => (
                <button
                  type="button"
                  key={result.path}
                  className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-left transition-colors"
                  style={{ color: 'var(--color-text)' }}
                  onClick={() => handleResultClick(result)}
                >
                  {result.type === 'dir'
                    ? <Folder size={16} style={{ color: 'var(--color-warning)' }} className="flex-shrink-0" />
                    : <File size={16} style={{ color: 'var(--color-text-muted)' }} className="flex-shrink-0" />
                  }
                  <div className="flex-1 min-w-0">
                    <p className="truncate">{result.name}</p>
                    <p className="text-xs truncate" style={{ color: 'var(--color-text-muted)' }}>{result.path}</p>
                  </div>
                  <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>{result.extension}</span>
                </button>
              ))
            )}
          </div>
        )}
      </div>

      {/* Right: actions */}
      <div ref={menuRef} className="flex items-center gap-1 flex-shrink-0">
        {/* Language */}
        <div className="relative" onKeyDown={e => handleDisclosureKeyDown(e, 'language')}>
          <button
            type="button"
            ref={languageTriggerRef}
            aria-label={t('header.language')}
            aria-expanded={openMenu === 'language'}
            onClick={() => toggleMenu('language')}
            className="p-1.5 rounded-md transition-colors hover:opacity-80"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            <Globe size={17} aria-hidden="true" />
          </button>
          <div data-header-menu hidden={openMenu !== 'language'} className="absolute right-0 top-full mt-1 z-50">
            <div
              className="rounded-lg py-1 min-w-[120px]"
              style={{
                backgroundColor: 'var(--color-surface)',
                border: '1px solid var(--color-border)',
                boxShadow: 'var(--shadow-lg)',
              }}
            >
              {supportedLangs.map(l => (
                <button
                  type="button"
                  key={l}
                  className="w-full px-3 py-1.5 text-sm text-left transition-colors"
                  style={{ color: lang === l ? 'var(--color-accent)' : 'var(--color-text)' }}
                  onClick={() => { setLang(l); setOpenMenu(null); }}
                >
                  {l === 'en' ? 'English' : l === 'zh' ? '中文' : '日本語'}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Theme toggle */}
        <button
          type="button"
          onClick={toggleTheme}
          aria-label={t('theme.toggle')}
          className="p-1.5 rounded-md transition-colors hover:opacity-80"
          style={{ color: 'var(--color-text-secondary)' }}
          title={t('theme.toggle')}
        >
          {theme === 'dark' ? <Sun size={17} aria-hidden="true" /> : <Moon size={17} aria-hidden="true" />}
        </button>

        {/* User / Login */}
        {role === 'guest' ? (
          <Link
            to="/login"
            className="px-2.5 py-1.5 text-sm rounded-md transition-colors"
            style={{ color: 'var(--color-text)' }}
          >
            {t('header.login')}
          </Link>
        ) : (
          <div className="relative" onKeyDown={e => handleDisclosureKeyDown(e, 'user')}>
            <button
              type="button"
              ref={userTriggerRef}
              aria-label={user?.username ?? t('perm.admin')}
              aria-expanded={openMenu === 'user'}
              onClick={() => toggleMenu('user')}
              className="flex items-center gap-1.5 px-2 py-1.5 text-sm rounded-md transition-colors"
              style={{ color: 'var(--color-text)' }}
            >
              <User size={16} aria-hidden="true" />
              <span className="max-w-[80px] truncate hidden sm:inline">{user?.username ?? t('perm.admin')}</span>
            </button>
            <div data-header-menu hidden={openMenu !== 'user'} className="absolute right-0 top-full mt-1 z-50">
              <div
                className="rounded-lg py-1 min-w-[140px]"
                style={{
                  backgroundColor: 'var(--color-surface)',
                  border: '1px solid var(--color-border)',
                  boxShadow: 'var(--shadow-lg)',
                }}
              >
                <div
                  className="px-3 py-1.5 text-xs"
                  style={{ color: 'var(--color-text-muted)', borderBottom: '1px solid var(--color-border)' }}
                >
                  {user?.username} · {role === 'admin' ? t('perm.admin') : t('perm.user')}
                </div>
                {role === 'admin' && (
                  <button type="button" onClick={() => navigate('/admin')} className="w-full px-3 py-1.5 text-sm text-left transition-colors" style={{ color: 'var(--color-text)' }}>
                    {t('header.admin')}
                  </button>
                )}
                <button
                  type="button"
                  onClick={logout}
                  className="w-full px-3 py-1.5 text-sm text-left transition-colors flex items-center gap-2"
                  style={{ color: 'var(--color-text)' }}
                >
                  <LogOut size={14} /> {t('header.logout')}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </header>
  );
}
