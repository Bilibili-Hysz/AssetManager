import { Link } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import { useI18n } from '../hooks/useI18n';
import { ActivityLogView } from '../components/admin/ActivityLog';
import { InviteManagement } from '../components/admin/InviteManagement';
import { OnlineUsers } from '../components/admin/OnlineUsers';
import { ShareManagement } from '../components/admin/ShareManagement';
import { UserManagement } from '../components/admin/UserManagement';

/**
 * Admin console — user, invite, share-link, and activity management.
 *
 * Guarded by ProtectedRoute capability="manage_users" (admin only) in App.tsx.
 * All child panels are self-contained: they read the auth context for the
 * API client and identity generation, so no props are threaded here.
 */
export default function AdminPage() {  const { t } = useI18n();
  const { role } = useAuth();

  if (role !== 'admin') {
    // The route guard should prevent this; keep a defensive fallback.
    return null;
  }

  const sections: Array<{ title: string; node: React.ReactNode }> = [
    { title: t('admin.users'), node: <UserManagement /> },
    { title: t('admin.invites'), node: <InviteManagement /> },
    { title: t('admin.shares'), node: <ShareManagement /> },
    { title: t('admin.activity'), node: <ActivityLogView /> },
    { title: t('admin.online'), node: <OnlineUsers /> },
  ];

  return (
    <div className="min-h-screen" style={{ background: 'var(--color-surface)' }}>
      <header
        className="flex items-center justify-between px-6 py-4"
        style={{ borderBottom: '1px solid var(--color-border)', background: 'var(--color-panel)' }}
      >
        <h1 className="text-xl font-bold" style={{ color: 'var(--color-heading)' }}>
          {t('admin.title')}
        </h1>
        <Link
          to="/browse"
          className="text-sm transition-colors"
          style={{ color: 'var(--color-accent)' }}
        >
          {t('admin.back')}
        </Link>
      </header>
      <main className="mx-auto max-w-5xl space-y-6 px-6 py-6">
        {sections.map(section => (
          <section
            key={section.title}
            className="rounded-lg p-4"
            style={{ background: 'var(--color-panel)', border: '1px solid var(--color-border)' }}
          >
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide" style={{ color: 'var(--color-muted)' }}>
              {section.title}
            </h2>
            {section.node}
          </section>
        ))}
      </main>
    </div>
  );
}
