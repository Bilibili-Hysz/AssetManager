import { Link } from 'react-router-dom';
import { useI18n } from '../hooks/useI18n';

/**
 * Catch-all 404 page, also rendered when a feature-flagged route is disabled.
 * Reuses existing i18n keys so no dictionary changes are needed
 * (`error.not_found`, `error.unknown` and `gallery.back_to_gallery` exist in
 * en/zh/ja).
 */
export default function NotFoundPage() {
  const { t } = useI18n();
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-[var(--color-bg)] px-4 text-center">
      <p className="text-6xl font-bold text-[var(--color-accent)]" aria-hidden="true">
        404
      </p>
      <h1 className="text-2xl font-semibold text-[var(--color-text)]">{t('error.not_found')}</h1>
      <p className="text-[var(--color-text-secondary)]">{t('error.unknown')}</p>
      <Link
        to="/"
        className="mt-2 rounded-lg px-4 py-2 font-medium transition-theme hover:opacity-90"
        style={{ backgroundColor: '#4f46e5', color: '#ffffff' }}
      >
        {t('gallery.back_to_gallery')}
      </Link>
    </div>
  );
}
