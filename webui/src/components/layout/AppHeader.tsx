import { useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react';
import { Command, File, FolderOpen, Globe, Images, LogOut, Moon, Search, Sun, User } from 'lucide-react';
import { Link, NavLink, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../../hooks/useAuth';
import { useI18n } from '../../hooks/useI18n';
import { useTheme } from '../../hooks/useTheme';
import { useSearch } from '../../hooks/useSearch';
import type { SearchResult } from '../../types/api';
import './Header.css';

export interface HeaderContextLink {
  to: string;
  label: string;
  end?: boolean;
}

export interface AppHeaderProps {
  galleryHref?: string;
  workspaceHref?: string;
  activeArea?: 'gallery' | 'workspace';
  contextNav?: HeaderContextLink[];
  onOpenPalette?: () => void;
  /**
   * Enter-to-submit bridge for the workspace search: BrowsePage turns the
   * typed text into a full three-source search result list. The debounced
   * quick-search dropdown below stays untouched for directory jumps.
   */
  onSearchSubmit?: (query: string) => void;
}

export function AppHeader({
  galleryHref = '/gallery',
  workspaceHref = '/browse',
  activeArea,
  contextNav = [],
  onOpenPalette,
  onSearchSubmit,
}: AppHeaderProps) {
  const { user, role, logout, serverInfo } = useAuth();
  const { t, lang, setLang, supportedLangs = [] } = useI18n();
  const { theme, toggleTheme } = useTheme();
  const { query, results, isSearching, setQuery, clear } = useSearch();
  const location = useLocation();
  const navigate = useNavigate();
  const searchRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const languageTriggerRef = useRef<HTMLButtonElement>(null);
  const userTriggerRef = useRef<HTMLButtonElement>(null);
  const [showResults, setShowResults] = useState(false);
  const [openMenu, setOpenMenu] = useState<'language' | 'user' | null>(null);
  const currentArea = activeArea ?? (location.pathname.startsWith('/browse') || location.pathname === '/detail' && new URLSearchParams(location.search).get('from') === 'workspace' ? 'workspace' : 'gallery');

  useEffect(() => {
    const handler = (event: MouseEvent) => {
      if (searchRef.current && !searchRef.current.contains(event.target as Node)) setShowResults(false);
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) setOpenMenu(null);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const isEditable = target instanceof HTMLInputElement
        || target instanceof HTMLTextAreaElement
        || target instanceof HTMLSelectElement
        || target?.isContentEditable;
      if (event.key === '/' && !event.ctrlKey && !event.metaKey && !isEditable) {
        event.preventDefault();
        document.querySelector<HTMLInputElement>('#header-search-input')?.focus();
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, []);

  const handleResultClick = (result: SearchResult) => {
    clear();
    setShowResults(false);
    if (result.type === 'dir') {
      navigate(currentArea === 'gallery'
        ? `/gallery/collection?path=${encodeURIComponent(result.path)}`
        : `/browse?path=${encodeURIComponent(result.path)}`);
      return;
    }
    const parts = result.path.split('/').filter(Boolean);
    const context = parts.slice(0, -1).join('/');
    navigate(`/detail?path=${encodeURIComponent(result.path)}&from=${currentArea}&context=${encodeURIComponent(context)}`);
  };

  const handleSearchKeyDown = (event: ReactKeyboardEvent<HTMLInputElement>) => {
    if (event.key !== 'Enter' || !onSearchSubmit) return;
    event.preventDefault();
    onSearchSubmit(query);
  };

  const toggleMenu = (menu: 'language' | 'user') => setOpenMenu(current => current === menu ? null : menu);

  const handleDisclosureKeyDown = (event: ReactKeyboardEvent, menu: 'language' | 'user') => {
    if (event.key !== 'Escape' || openMenu !== menu) return;
    event.preventDefault();
    setOpenMenu(null);
    (menu === 'language' ? languageTriggerRef : userTriggerRef).current?.focus();
  };

  return (
    <header className="app-header">
      <Link to={galleryHref} className="app-header-brand" aria-label={t('gallery.open_home')}>
        <span className="app-header-brand-mark"><Images size={17} aria-hidden="true" /></span>
        <span className="app-header-brand-name">{serverInfo?.share_name ?? 'AssetsManager'}</span>
      </Link>

      <div className="app-header-navigation">
        <nav className="app-header-area-nav" aria-label={t('header.primary_navigation')}>
          <Link to={galleryHref} aria-label={t('gallery.nav_home')} aria-current={currentArea === 'gallery' ? 'page' : undefined} className={`app-header-area-link ${currentArea === 'gallery' ? 'app-header-area-link-active' : ''}`}>
            <Images size={15} aria-hidden="true" />
            <span>{t('gallery.nav_home')}</span>
          </Link>
          <Link to={workspaceHref} aria-label={t('gallery.workspace')} aria-current={currentArea === 'workspace' ? 'page' : undefined} className={`app-header-area-link ${currentArea === 'workspace' ? 'app-header-area-link-active' : ''}`}>
            <FolderOpen size={15} aria-hidden="true" />
            <span>{t('gallery.workspace')}</span>
          </Link>
        </nav>
        {contextNav.length > 0 && (
          <nav className="app-header-context-nav" aria-label={t('gallery.nav_aria')}>
            {contextNav.map(item => (
              <NavLink key={item.to} to={item.to} end={item.end} className={({ isActive }) => `app-header-context-link ${isActive ? 'app-header-context-link-active' : ''}`}>
                {item.label}
              </NavLink>
            ))}
          </nav>
        )}
      </div>

      <div ref={searchRef} className="app-header-search">
        <Search size={15} className="app-header-search-icon" aria-hidden="true" />
        <input
          id="header-search-input"
          type="search"
          aria-label={t('header.search')}
          value={query}
          onChange={event => { setQuery(event.target.value); setShowResults(true); }}
          onKeyDown={handleSearchKeyDown}
          onFocus={() => { if (results.length > 0) setShowResults(true); }}
          placeholder={t('header.search')}
        />
        {onOpenPalette && (
          <button type="button" className="app-header-command" onClick={onOpenPalette} aria-label={`${t('header.search')} (${t('header.search_shortcut')})`} title={`${t('header.search')} (${t('header.search_shortcut')})`}>
            <Command size={14} aria-hidden="true" />
            <kbd>{t('header.search_shortcut')}</kbd>
          </button>
        )}
        {showResults && (query.trim() || isSearching) && (
          <div className="app-header-search-results">
            {isSearching ? (
              <div className="app-header-search-message">{t('browse.loading')}</div>
            ) : results.length === 0 ? (
              <div className="app-header-search-message">{t('header.no_results')}</div>
            ) : results.map(result => (
              <button type="button" key={result.path} className="app-header-search-result" onClick={() => handleResultClick(result)}>
                {result.type === 'dir' ? <FolderOpen size={16} className="app-header-search-result-icon" aria-hidden="true" /> : <File size={16} className="app-header-search-file-icon" aria-hidden="true" />}
                <span className="app-header-search-result-copy">
                  <span>{result.name}</span>
                  <small>{result.path}</small>
                </span>
                <small>{result.extension}</small>
              </button>
            ))}
          </div>
        )}
      </div>

      <div ref={menuRef} className="app-header-actions">
        <div className="app-header-menu-wrap" onKeyDown={event => handleDisclosureKeyDown(event, 'language')}>
          <button type="button" ref={languageTriggerRef} className="app-header-icon-button" aria-label={t('header.language')} aria-haspopup="menu" aria-expanded={openMenu === 'language'} onClick={() => toggleMenu('language')}>
            <Globe size={17} aria-hidden="true" />
          </button>
          <div className="app-header-menu" role="menu" hidden={openMenu !== 'language'}>
            {supportedLangs.map(language => (
              <button type="button" role="menuitem" key={language} className={lang === language ? 'app-header-menu-item-active' : ''} onClick={() => { setLang(language); setOpenMenu(null); }}>
                {language === 'en' ? 'English' : language === 'zh' ? '中文' : '日本語'}
              </button>
            ))}
          </div>
        </div>

        <button type="button" className="app-header-icon-button" onClick={toggleTheme} aria-label={theme === 'dark' ? t('gallery.theme_light') : t('gallery.theme_dark')} title={theme === 'dark' ? t('gallery.theme_light') : t('gallery.theme_dark')}>
          {theme === 'dark' ? <Sun size={17} aria-hidden="true" /> : <Moon size={17} aria-hidden="true" />}
        </button>

        {role === 'guest' ? (
          serverInfo?.auth_enabled ? <Link to="/login" className="app-header-login-link">{t('header.login')}</Link> : null
        ) : (
          <div className="app-header-menu-wrap" onKeyDown={event => handleDisclosureKeyDown(event, 'user')}>
            <button type="button" ref={userTriggerRef} className="app-header-user-button" aria-label={user?.username ?? t('perm.admin')} aria-haspopup="menu" aria-expanded={openMenu === 'user'} onClick={() => toggleMenu('user')}>
              <User size={16} aria-hidden="true" />
              <span>{user?.username ?? t('perm.admin')}</span>
            </button>
            <div className="app-header-menu app-header-user-menu" role="menu" hidden={openMenu !== 'user'}>
              <div className="app-header-menu-meta">{user?.username} · {role === 'admin' ? t('perm.admin') : t('perm.user')}</div>
              {role === 'admin' && (
                <button type="button" onClick={() => navigate('/admin')}>
                  {t('header.admin')}
                </button>
              )}
              <button type="button" onClick={logout}><LogOut size={14} aria-hidden="true" /> {t('header.logout')}</button>
            </div>
          </div>
        )}
      </div>
    </header>
  );
}
