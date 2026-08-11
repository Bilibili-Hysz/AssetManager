import { ArrowDown, ArrowUp, ImageOff, Plus, Trash2 } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { assetThumbnailUrl } from '../../hooks/useCommerce';
import { useI18n } from '../../hooks/useI18n';

export interface SellerGalleryEditorProps {
  coverPath: string;
  galleryPaths: string[];
  buildUrl: (path: string) => string;
  onChange: (value: { coverPath: string; galleryPaths: string[] }) => void;
}

function normalizePath(value: string): string {
  return value.trim().replace(/\\/g, '/');
}

function isValidLibraryPath(value: string): boolean {
  const path = normalizePath(value);
  return Boolean(path) && !path.startsWith('/') && !/^https?:\/\//i.test(path) && !path.split('/').some(segment => segment === '..');
}

function isDuplicate(path: string, paths: string[], index: number): boolean {
  const normalized = normalizePath(path).toLowerCase();
  return Boolean(normalized) && paths.some((candidate, candidateIndex) => candidateIndex !== index && normalizePath(candidate).toLowerCase() === normalized);
}

export default function SellerGalleryEditor({ coverPath, galleryPaths, buildUrl, onChange }: SellerGalleryEditorProps) {
  const { t } = useI18n();
  const [coverDraft, setCoverDraft] = useState(coverPath);
  const [items, setItems] = useState(galleryPaths);
  const [newPath, setNewPath] = useState('');
  const [failedPreviews, setFailedPreviews] = useState<Record<string, boolean>>({});

  useEffect(() => setCoverDraft(coverPath), [coverPath]);
  useEffect(() => setItems(galleryPaths), [galleryPaths]);

  const coverError = coverDraft.trim() && !isValidLibraryPath(coverDraft)
    ? t('seller.gallery_path_relative')
    : '';
  const newPathError = newPath.trim() && !isValidLibraryPath(newPath)
    ? t('seller.gallery_path_relative')
    : newPath.trim() && (normalizePath(newPath).toLowerCase() === normalizePath(coverDraft).toLowerCase() || isDuplicate(newPath, items, -1))
      ? t('seller.gallery_path_duplicate')
      : '';
  const itemErrors = useMemo(() => items.map((path, index) => {
    if (!path.trim()) return t('seller.gallery_path_required');
    if (!isValidLibraryPath(path)) return t('seller.gallery_path_relative');
    if (normalizePath(path).toLowerCase() === normalizePath(coverDraft).toLowerCase()) return t('seller.gallery_path_duplicate_cover');
    if (isDuplicate(path, items, index)) return t('seller.gallery_path_duplicate_item');
    return '';
  }), [coverDraft, items]);

  const emit = (nextCover: string, nextItems: string[]) => {
    onChange({ coverPath: nextCover, galleryPaths: nextItems });
  };

  const updateCover = (value: string) => {
    setCoverDraft(value);
    emit(value, items);
  };

  const updateItem = (index: number, value: string) => {
    const next = items.map((path, itemIndex) => itemIndex === index ? value : path);
    setItems(next);
    emit(coverDraft, next);
  };

  const addItem = () => {
    if (newPathError || !newPath.trim()) return;
    const next = [...items, normalizePath(newPath)];
    setItems(next);
    setNewPath('');
    emit(coverDraft, next);
  };

  const removeItem = (index: number) => {
    const next = items.filter((_, itemIndex) => itemIndex !== index);
    setItems(next);
    emit(coverDraft, next);
  };

  const moveItem = (index: number, offset: -1 | 1) => {
    const targetIndex = index + offset;
    if (targetIndex < 0 || targetIndex >= items.length) return;
    const next = [...items];
    const current = next[index];
    const target = next[targetIndex];
    if (current === undefined || target === undefined) return;
    next[index] = target;
    next[targetIndex] = current;
    setItems(next);
    emit(coverDraft, next);
  };

  const preview = (path: string, label: string) => {
    const normalized = normalizePath(path);
    const url = isValidLibraryPath(normalized)
      ? assetThumbnailUrl(normalized, 256, buildUrl)
      : '';
    if (!url) {
      return <div className="flex h-20 w-20 shrink-0 items-center justify-center rounded-lg border border-dashed border-[var(--color-border)] bg-[var(--color-surface-muted)] text-xs text-[var(--color-text-secondary)]" aria-label={`${label} preview unavailable`}><ImageOff size={18} aria-hidden="true" /></div>;
    }
    if (failedPreviews[normalized]) {
      return <div className="flex h-20 w-20 shrink-0 items-center justify-center rounded-lg border border-dashed border-[var(--color-border)] bg-[var(--color-surface-muted)] px-1 text-center text-[10px] text-[var(--color-text-secondary)]" aria-label={`${label} preview unavailable`}>{t('landing.previews_unavailable')}</div>;
    }
    return <img src={url} alt={`${label}: ${normalized}`} className="h-20 w-20 shrink-0 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-muted)] object-cover" onError={() => setFailedPreviews(current => ({ ...current, [normalized]: true }))} />;
  };

  return (
    <fieldset className="seller-gallery-editor min-w-0" aria-describedby="seller-gallery-help">
      <legend className="mb-2 font-medium">{t('seller.gallery_paths')}</legend>
      <p id="seller-gallery-help" className="mb-3 text-sm text-[var(--color-text-secondary)]">{t('seller.gallery_paths_help')} {t('seller.gallery_paths_note')}</p>

      <div className="mb-4 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-muted)] p-3">
        <div className="mb-2 flex items-center justify-between gap-2"><strong>{t('seller.gallery_cover')}</strong><span className="text-xs text-[var(--color-text-secondary)]">{t('info.path')}</span></div>
        <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-center">
          {preview(coverDraft, t('seller.gallery_cover'))}
          <label className="min-w-0 flex-1"><span className="sr-only">{t('seller.cover_path')}</span><input className="w-full" value={coverDraft} onChange={event => updateCover(event.target.value)} placeholder={t('seller.gallery_paths_placeholder')} aria-invalid={Boolean(coverError)} aria-describedby={coverError ? 'seller-cover-error' : undefined} /></label>
        </div>
        {coverError && <p id="seller-cover-error" className="mt-2 text-sm text-[var(--color-danger)]" role="alert">{coverError}</p>}
      </div>

      <div className="mb-3 flex items-center justify-between gap-2"><strong>{t('seller.gallery')}</strong><span className="text-xs text-[var(--color-text-secondary)]">{items.length} / 20</span></div>
      <div className="grid min-w-0 grid-cols-1 gap-2 sm:grid-cols-2" role="list" aria-label={t('seller.gallery_preview')}>
        {items.map((path, index) => (
          // H2: key must NOT include the editable value (`${index}-${path}` re-created the row
          // on every keystroke, dropping input focus). Rows hold no local state keyed by path
          // (preview failure flags are keyed by path in a parent record), so `index` is stable.
          <div key={index} role="listitem" tabIndex={0} className="flex min-w-0 items-center gap-2 rounded-xl border border-[var(--color-border)] p-2 outline-none focus-within:ring-2 focus-within:ring-[var(--color-accent)] focus:ring-2 focus:ring-[var(--color-accent)]" onKeyDown={event => { if (event.key === 'ArrowUp') { event.preventDefault(); moveItem(index, -1); } if (event.key === 'ArrowDown') { event.preventDefault(); moveItem(index, 1); } if (event.key === 'Delete' && event.target === event.currentTarget) { event.preventDefault(); removeItem(index); } }}>
            {preview(path, `${t('seller.gallery')} ${index + 1}`)}
            <div className="min-w-0 flex-1">
              <label className="block"><span className="sr-only">{t('seller.gallery_image_path', index + 1)}</span><input className="w-full min-w-0" value={path} onChange={event => updateItem(index, event.target.value)} aria-invalid={Boolean(itemErrors[index])} aria-describedby={itemErrors[index] ? `seller-gallery-error-${index}` : undefined} /></label>
              {itemErrors[index] && <p id={`seller-gallery-error-${index}`} className="mt-1 text-xs text-[var(--color-danger)]" role="alert">{itemErrors[index]}</p>}
            </div>
            <div className="flex shrink-0 flex-col gap-1">
              <button type="button" className="storefront-button storefront-button-ghost !p-1" aria-label={t('seller.move_gallery_image_up', index + 1)} onClick={() => moveItem(index, -1)} disabled={index === 0}><ArrowUp size={14} /></button>
              <button type="button" className="storefront-button storefront-button-ghost !p-1" aria-label={t('seller.move_gallery_image_down', index + 1)} onClick={() => moveItem(index, 1)} disabled={index === items.length - 1}><ArrowDown size={14} /></button>
              <button type="button" className="storefront-button storefront-button-ghost !p-1" aria-label={t('seller.delete_gallery_image', index + 1)} onClick={() => removeItem(index)}><Trash2 size={14} /></button>
            </div>
          </div>
        ))}
      </div>

      <div className="mt-3 flex min-w-0 flex-col gap-2 sm:flex-row">
        <label className="min-w-0 flex-1"><span className="sr-only">{t('seller.new_gallery_image_path')}</span><input className="w-full" value={newPath} onChange={event => setNewPath(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') { event.preventDefault(); addItem(); } }} placeholder={t('seller.gallery_paths_placeholder')} aria-invalid={Boolean(newPathError)} aria-describedby={newPathError ? 'seller-new-gallery-error' : undefined} /></label>
        <button type="button" className="storefront-button storefront-button-ghost justify-center" onClick={addItem} disabled={items.length >= 20 || Boolean(newPathError) || !newPath.trim()}><Plus size={15} /> {t('info.add_tag')}</button>
      </div>
      {newPathError && <p id="seller-new-gallery-error" className="mt-2 text-sm text-[var(--color-danger)]" role="alert">{newPathError}</p>}
    </fieldset>
  );
}
