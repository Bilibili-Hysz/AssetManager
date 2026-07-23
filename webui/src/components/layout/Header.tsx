import { useRef, useState, useEffect } from 'react';
import { Search, LogOut, Sun, Moon, Globe, User, File, Folder, PanelLeft, PanelRight } from 'lucide-react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../../hooks/useAuth';
import { useI18n } from '../../hooks/useI18n';
import { useTheme } from '../../hooks/useTheme';
import { useSearch } from '../../hooks/useSearch';
import type { SearchResult } from '../../types/api';

interface HeaderProps {
  onSidebarToggle: () => void;
  onInfoToggle: () => void;
  sidebarOpen: boolean;
  infoOpen: boolean;
}

export function Header({ onSidebarToggle, onInfoToggle, sidebarOpen, infoOpen }: HeaderProps) {
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
  const sidebarToggleLabel = t(sidebarOpen ? 'action.close_sidebar' : 'action.open_sidebar');
  const infoToggleLabel = t(infoOpen ? 'action.close_info' : 'mobile.info');

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
    <header className="flex items-center gap-3 px-4 h-14 border-b border-slate-700/50 bg-slate-900/80 backdrop-blur-md">
      {/* Left: sidebar toggle + brand */}
      <div className="flex items-center gap-2 flex-shrink-0">
        <button
          onClick={onSidebarToggle}
          aria-label={sidebarToggleLabel}
          className="p-1.5 text-slate-400 hover:text-white hover:bg-slate-800/50 rounded-md transition-colors"
          title={sidebarToggleLabel}
        >
          <PanelLeft size={18} aria-hidden="true" />
        </button>
        <Link to="/" className="flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-md bg-indigo-500 flex items-center justify-center text-sm font-bold text-white">
            A
          </div>
          <span className="text-sm font-semibold text-slate-100 hidden sm:inline">
            {serverInfo?.share_name ?? 'AssetManager'}
          </span>
        </Link>
      </div>

      {/* Center: search */}
      <div ref={searchRef} className="flex-1 max-w-md relative">
        <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" aria-hidden="true" />
        <input
          id="header-search-input"
          type="text"
          role="searchbox"
          aria-label={t('header.search')}
          value={query}
          onChange={e => { setQuery(e.target.value); setShowResults(true); }}
          onFocus={() => { if (results.length > 0) setShowResults(true); }}
          placeholder={`${t('header.search')}...`}
          className="w-full pl-9 pr-4 py-1.5 bg-slate-800/50 border border-slate-700/50 rounded-lg text-sm
            text-slate-200 placeholder-slate-500 focus:outline-none focus:border-indigo-500/50 focus:bg-slate-800/80 transition-colors"
        />
        {/* Search results dropdown */}
        {showResults && (query.trim() || isSearching) && (
          <div className="absolute top-full left-0 right-0 mt-1.5 bg-slate-800 border border-slate-600/50 rounded-lg shadow-xl max-h-80 overflow-auto z-50">
            {isSearching ? (
              <div className="p-3 text-center text-sm text-slate-500">{t('browse.loading')}</div>
            ) : results.length === 0 ? (
              <div className="p-3 text-center text-sm text-slate-500">{t('header.no_results')}</div>
            ) : (
              results.map(result => (
                <button
                  key={result.path}
                  className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-left text-slate-200 hover:bg-slate-700/50 transition-colors"
                  onClick={() => handleResultClick(result)}
                >
                  {result.type === 'dir'
                    ? <Folder size={16} className="text-amber-400 flex-shrink-0" />
                    : <File size={16} className="text-slate-500 flex-shrink-0" />
                  }
                  <div className="flex-1 min-w-0">
                    <p className="truncate">{result.name}</p>
                    <p className="text-xs text-slate-500 truncate">{result.path}</p>
                  </div>
                  <span className="text-xs text-slate-600">{result.extension}</span>
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
          <button ref={languageTriggerRef} aria-label={t('header.language')} aria-expanded={openMenu === 'language'} onClick={() => toggleMenu('language')} className="p-1.5 text-slate-400 hover:text-white hover:bg-slate-800/50 rounded-md transition-colors">
            <Globe size={17} aria-hidden="true" />
          </button>
          <div data-header-menu hidden={openMenu !== 'language'} className="absolute right-0 top-full mt-1 z-50">
            <div className="bg-slate-800 border border-slate-600/50 rounded-lg py-1 min-w-[120px] shadow-xl">
              {supportedLangs.map(l => (
                <button
                  key={l}
                  className={`w-full px-3 py-1.5 text-sm text-left hover:bg-slate-700/50 transition-colors ${
                    lang === l ? 'text-indigo-400' : 'text-slate-300'
                  }`}
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
          onClick={toggleTheme}
          aria-label={t('theme.toggle')}
          className="p-1.5 text-slate-400 hover:text-white hover:bg-slate-800/50 rounded-md transition-colors"
          title={t('theme.toggle')}
        >
          {theme === 'dark' ? <Sun size={17} aria-hidden="true" /> : <Moon size={17} aria-hidden="true" />}
        </button>

        {/* Info panel toggle */}
        <button
          onClick={onInfoToggle}
          aria-label={infoToggleLabel}
          className="p-1.5 text-slate-400 hover:text-white hover:bg-slate-800/50 rounded-md transition-colors"
          title={infoToggleLabel}
        >
          <PanelRight size={17} aria-hidden="true" />
        </button>

        {/* User / Login */}
        {role === 'guest' ? (
          <Link to="/login" className="px-2.5 py-1.5 text-sm text-slate-300 hover:text-white hover:bg-slate-800/50 rounded-md transition-colors">
            {t('header.login')}
          </Link>
        ) : (
          <div className="relative" onKeyDown={e => handleDisclosureKeyDown(e, 'user')}>
            <button ref={userTriggerRef} aria-label={user?.username ?? t('perm.admin')} aria-expanded={openMenu === 'user'} onClick={() => toggleMenu('user')} className="flex items-center gap-1.5 px-2 py-1.5 text-sm text-slate-300 hover:text-white hover:bg-slate-800/50 rounded-md transition-colors">
              <User size={16} aria-hidden="true" />
              <span className="max-w-[80px] truncate hidden sm:inline">{user?.username ?? t('perm.admin')}</span>
            </button>
            <div data-header-menu hidden={openMenu !== 'user'} className="absolute right-0 top-full mt-1 z-50">
              <div className="bg-slate-800 border border-slate-600/50 rounded-lg py-1 min-w-[140px] shadow-xl">
                <div className="px-3 py-1.5 text-xs text-slate-500 border-b border-slate-700/50">
                  {user?.username} · {role === 'admin' ? t('perm.admin') : t('perm.user')}
                </div>
                {role === 'admin' && (
                  <button className="w-full px-3 py-1.5 text-sm text-left text-slate-300 hover:bg-slate-700/50 transition-colors">
                    {t('header.admin')}
                  </button>
                )}
                <button
                  onClick={logout}
                  className="w-full px-3 py-1.5 text-sm text-left text-slate-300 hover:bg-slate-700/50 transition-colors flex items-center gap-2"
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
