import type { ReactNode } from 'react';
import type { GalleryEntry } from '../../types/api';

interface GalleryTiledGridProps {
  entries: GalleryEntry[];
  children: (entry: GalleryEntry) => ReactNode;
}

/** Uniform square grid for predictable artwork scanning and responsive layout. */
export function GalleryTiledGrid({ entries, children }: GalleryTiledGridProps) {
  return (
    <div className="gallery-tiled-grid">
      {entries.map(entry => (
        <div key={entry.path} className="gallery-tile-slot">{children(entry)}</div>
      ))}
    </div>
  );
}
