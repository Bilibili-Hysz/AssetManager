import type { ReactNode } from 'react';

interface GallerySectionProps {
  title: string;
  action?: ReactNode;
  children: ReactNode;
}

export function GallerySection({ title, action, children }: GallerySectionProps) {
  return (
    <section className="gallery-section">
      <div className="gallery-section-heading">
        <h2>{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}
