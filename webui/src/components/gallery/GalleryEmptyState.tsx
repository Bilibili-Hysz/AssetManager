import { Images, RefreshCw, Wrench } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useI18n } from '../../hooks/useI18n';

interface GalleryEmptyStateProps {
  title: string;
  description: string;
  onRetry?: () => void;
}

export function GalleryEmptyState({ title, description, onRetry }: GalleryEmptyStateProps) {
  const { t } = useI18n();
  return (
    <div className="gallery-empty-state">
      <Images size={32} />
      <h2>{title}</h2>
      <p>{description}</p>
      <div className="gallery-empty-actions">
        {onRetry && (
          <button type="button" onClick={onRetry} className="gallery-secondary-button">
            <RefreshCw size={15} /> {t('gallery.retry')}
          </button>
        )}
        <Link to="/browse" className="gallery-secondary-button">
          <Wrench size={15} /> {t('gallery.open_workspace_action')}
        </Link>
      </div>
    </div>
  );
}
