import { RefreshCw, Wrench } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useI18n } from '../../hooks/useI18n';
import { EmptyState } from '../ui/EmptyState';

interface GalleryEmptyStateProps {
  title: string;
  description: string;
  onRetry?: () => void;
}

export function GalleryEmptyState({ title, description, onRetry }: GalleryEmptyStateProps) {
  const { t } = useI18n();

  return (
    <EmptyState
      type="directory"
      title={title}
      description={description}
      className="gallery-empty-state"
      primaryAction={
        onRetry
          ? {
              label: t('gallery.retry'),
              onClick: onRetry,
              icon: <RefreshCw size={15} />,
              className: 'gallery-secondary-button',
            }
          : undefined
      }
      secondaryAction={
        <Link to="/browse" className="empty-state-btn empty-state-btn-secondary gallery-secondary-button">
          <Wrench size={15} /> {t('gallery.open_workspace_action')}
        </Link>
      }
    />
  );
}
