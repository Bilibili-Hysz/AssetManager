import { useCallback, useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react';
import { ArrowDown, ArrowUp, CornerDownLeft, File, Folder, Search, X } from 'lucide-react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useI18n } from '../../hooks/useI18n';
import { useSearch } from '../../hooks/useSearch';
import { useDialogFocus } from '../../hooks/useDialogFocus';
import type { SearchResult } from '../../types/api';
import './CommandPalette.css';

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
}

function parentPath(path: string) {
  const parts = path.split('/').filter(Boolean);
  return parts.slice(0, -1).join('/');
}

function openSearchResult(navigate: ReturnType<typeof useNavigate>, item: SearchResult, mode: 'gallery' | 'workspace') {
  if (item.type === 'dir') {
    navigate(mode === 'gallery'
      ? '/gallery/collection?path=' + encodeURIComponent(item.path)
      : '/browse?path=' + encodeURIComponent(item.path));
    return;
  }
  const context = parentPath(item.path);
  navigate('/detail?path=' + encodeURIComponent(item.path) + '&from=' + mode + '&context=' + encodeURIComponent(context));
}

export function CommandPalette({ open, onClose }: CommandPaletteProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const { t } = useI18n();
  const { query, results, isSearching, setQuery, clear } = useSearch();
  const mode = location.pathname.startsWith('/browse')
    || (location.pathname === '/detail' && new URLSearchParams(location.search).get('from') === 'workspace')
    ? 'workspace'
    : 'gallery';
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const dialogRef = useDialogFocus(open, onClose);

  const close = useCallback(() => {
    clear();
    onClose();
  }, [clear, onClose]);

  useEffect(() => {
    if (!open) return;
    clear();
    setSelectedIndex(0);
    const focusTimer = window.setTimeout(() => inputRef.current?.focus(), 40);
    return () => window.clearTimeout(focusTimer);
  }, [clear, open]);

  useEffect(() => {
    setSelectedIndex(previous => results.length === 0 ? 0 : Math.min(previous, results.length - 1));
  }, [results.length]);

  useEffect(() => {
    const list = listRef.current;
    if (!list || results.length === 0) return;
    const selected = list.children[selectedIndex] as HTMLElement | undefined;
    selected?.scrollIntoView({ block: 'nearest' });
  }, [results, selectedIndex]);

  const openResult = useCallback((item: SearchResult) => {
    close();
    openSearchResult(navigate, item, mode);
  }, [close, mode, navigate]);

  const handleKeyDown = useCallback((event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      close();
      return;
    }
    if (event.key === 'ArrowDown' && results.length > 0) {
      event.preventDefault();
      setSelectedIndex(previous => Math.min(previous + 1, results.length - 1));
      return;
    }
    if (event.key === 'ArrowUp' && results.length > 0) {
      event.preventDefault();
      setSelectedIndex(previous => Math.max(previous - 1, 0));
      return;
    }
    if (event.key === 'Enter' && results.length > 0) {
      event.preventDefault();
      const selected = results[selectedIndex];
      if (selected) openResult(selected);
    }
  }, [close, openResult, results, selectedIndex]);

  if (!open) return null;

  return (
    <div
      ref={dialogRef}
      className="command-palette-overlay"
      role="dialog"
      aria-modal="true"
      aria-label={t('commands.title')}
      tabIndex={-1}
      onClick={event => { if (event.target === event.currentTarget) close(); }}
      onKeyDown={handleKeyDown}
    >
      <div className="command-palette">
        <div className="command-palette-input-row">
          <Search size={18} className="command-palette-input-icon" aria-hidden="true" />
          <input
            ref={inputRef}
            className="command-palette-input"
            type="search"
            role="combobox"
            aria-label={t('commands.placeholder')}
            aria-autocomplete="list"
            aria-controls="command-palette-results"
            aria-expanded={results.length > 0}
            aria-activedescendant={results[selectedIndex] ? 'command-result-' + selectedIndex : undefined}
            value={query}
            onChange={event => setQuery(event.target.value)}
            placeholder={t('commands.placeholder')}
            autoComplete="off"
          />
          {query && (
            <button type="button" className="command-palette-clear" onClick={() => { clear(); inputRef.current?.focus(); }} aria-label={t('action.close')}>
              <X size={16} aria-hidden="true" />
            </button>
          )}
          <kbd className="command-palette-shortcut">ESC</kbd>
        </div>

        <div className="command-palette-mode" aria-live="polite">
          {t(mode === 'gallery' ? 'commands.mode_gallery' : 'commands.mode_workspace')}
        </div>

        {/* The container is only a listbox when it actually holds options;
            the empty/searching/no-results states are plain message blocks. */}
        <div id="command-palette-results" ref={listRef} className="command-palette-results" role={results.length > 0 ? 'listbox' : undefined} aria-busy={isSearching}>
          {!query.trim() && !isSearching ? (
            <div className="command-palette-empty">
              <strong>{t('commands.empty_title')}</strong>
              <span>{t('commands.empty_hint')}</span>
            </div>
          ) : isSearching ? (
            <div className="command-palette-message" role="status">
              <span className="command-palette-spinner" aria-hidden="true" />
              <span>{t('commands.searching')}</span>
            </div>
          ) : results.length === 0 ? (
            <div className="command-palette-message">{t('commands.no_results', query.trim())}</div>
          ) : (
            results.map((item, index) => {
              const isDirectory = item.type === 'dir';
              const isSelected = index === selectedIndex;
              return (
                <button
                  type="button"
                  key={item.path}
                  id={'command-result-' + index}
                  className={'command-palette-result ' + (isSelected ? 'command-palette-result-selected' : '')}
                  role="option"
                  aria-selected={isSelected}
                  data-testid={'command-result-' + index}
                  onClick={() => openResult(item)}
                  onMouseEnter={() => setSelectedIndex(index)}
                >
                  {isDirectory ? <Folder size={17} className="command-palette-result-folder" aria-hidden="true" /> : <File size={17} className="command-palette-result-file" aria-hidden="true" />}
                  <span className="command-palette-result-copy">
                    <strong>{item.name}</strong>
                    <small>{item.path || '/'}</small>
                  </span>
                  <span className="command-palette-result-kind">{isDirectory ? t('commands.folder') : t('commands.file')}</span>
                  {isSelected && <CornerDownLeft size={14} className="command-palette-result-enter" aria-hidden="true" />}
                </button>
              );
            })
          )}
        </div>

        <div className="command-palette-footer">
          <span><ArrowUp size={12} aria-hidden="true" /><ArrowDown size={12} aria-hidden="true" /> {t('commands.navigate')}</span>
          <span><CornerDownLeft size={12} aria-hidden="true" /> {t('commands.open')}</span>
          <span><kbd>ESC</kbd> {t('commands.close')}</span>
        </div>
      </div>
    </div>
  );
}
