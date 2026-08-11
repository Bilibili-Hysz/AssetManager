import { Columns3, Grid2X2, Rows3 } from 'lucide-react';
import type { ReactNode } from 'react';
import { useI18n } from '../../hooks/useI18n';

export type GalleryViewMode = 'masonry' | 'grid' | 'compact';
export type GalleryMediaMode = 'natural' | 'uniform' | 'square' | 'compact';

export const GALLERY_VIEW_STORAGE_KEY = 'am_gallery_view';

export function readGalleryView(): GalleryViewMode {
  try {
    const value = localStorage.getItem(GALLERY_VIEW_STORAGE_KEY);
    if (value === 'masonry' || value === 'grid' || value === 'compact') return value;
  } catch { /* localStorage is optional */ }
  return 'masonry';
}

export function galleryMediaMode(view: GalleryViewMode): GalleryMediaMode {
  if (view === 'grid') return 'uniform';
  if (view === 'compact') return 'compact';
  return 'square';
}

interface GalleryViewControlsProps {
  value: GalleryViewMode;
  onChange: (value: GalleryViewMode) => void;
}

export function GalleryViewControls({ value, onChange }: GalleryViewControlsProps) {
  const { t } = useI18n();
  const options: Array<{ value: GalleryViewMode; label: string; icon: ReactNode }> = [
    { value: 'masonry', label: t('gallery.view_masonry'), icon: <Columns3 size={15} aria-hidden="true" /> },
    { value: 'grid', label: t('gallery.view_grid'), icon: <Grid2X2 size={15} aria-hidden="true" /> },
    { value: 'compact', label: t('gallery.view_compact'), icon: <Rows3 size={15} aria-hidden="true" /> },
  ];

  return (
    <fieldset className="gallery-view-controls">
      <legend className="sr-only">{t('gallery.view_mode')}</legend>
      {options.map(option => (
        <button
          key={option.value}
          type="button"
          className={`gallery-view-button ${value === option.value ? 'gallery-view-button-active' : ''}`}
          onClick={() => onChange(option.value)}
          aria-pressed={value === option.value}
          aria-label={option.label}
          title={option.label}
        >
          {option.icon}
          <span>{option.label}</span>
        </button>
      ))}
    </fieldset>
  );
}
