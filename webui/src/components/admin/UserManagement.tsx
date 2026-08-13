import { useState, useMemo } from 'react';
import { Shield, ShieldOff } from 'lucide-react';
import { useAuth } from '../../hooks/useAuth';
import { createUsersApi } from '../../api/users';
import type { User } from '../../types/api';
import { useI18n } from '../../hooks/useI18n';
import { useToast } from '../ui/Toast';
import { useCachedQuery } from '../../hooks/useCachedQuery';

// NOTE: this admin panel is not yet mounted on any route — wiring the Admin section
// into the router is a later task (see D2 in the component backlog).

export function UserManagement() {
  const { api } = useAuth();
  const usersApi = useMemo(() => createUsersApi(api), [api]);
  const { t } = useI18n();
  const { showToast } = useToast();
  const { data, refresh } = useCachedQuery<User[]>({
    key: ['users'],
    queryFn: () => usersApi.list().then(res => res.users),
    domains: ['users'],
  });
  const users = data ?? [];
  const [pendingId, setPendingId] = useState<number | null>(null);

  const handleToggle = async (id: number, current: boolean) => {
    // E2: require explicit confirmation before enabling/disabling an account.
    const username = users.find(candidate => candidate.id === id)?.username ?? String(id);
    if (!window.confirm(current ? t('admin.confirm_disable_user', username) : t('admin.confirm_enable_user', username))) return;
    setPendingId(id);
    try {
      await usersApi.toggleUser(id, !current);
      refresh();
    } catch {
      showToast(t('admin.toggle_user_failed'), 'error');
    } finally {
      setPendingId(null);
    }
  };

  return (
    <div>
      <h3 className="text-lg font-semibold text-white mb-4">{t('admin.users')}</h3>
      {users.length === 0 ? (
        <p className="text-sm text-slate-500">{t('admin.no_users')}</p>
      ) : (
        <div className="border border-slate-700/50 rounded-lg overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b border-slate-700/50 bg-slate-800/50">
                <th className="text-left text-xs text-slate-500 font-medium px-4 py-2">{t('auth.username')}</th>
                <th className="text-left text-xs text-slate-500 font-medium px-4 py-2">{t('perm.role')}</th>
                <th className="text-left text-xs text-slate-500 font-medium px-4 py-2">Status</th>
                <th className="text-right text-xs text-slate-500 font-medium px-4 py-2">{t('action.actions')}</th>
              </tr>
            </thead>
            <tbody>
              {users.map(user => (
                <tr key={user.id} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                  <td className="px-4 py-2.5 text-sm text-slate-200">{user.username}</td>
                  <td className="px-4 py-2.5 text-sm text-slate-400">{user.role}</td>
                  <td className="px-4 py-2.5 text-sm">
                    <span className={`px-2 py-0.5 rounded-full text-xs ${user.active ? 'bg-emerald-500/10 text-emerald-400' : 'bg-red-500/10 text-red-400'}`}>
                      {user.active ? t('admin.enable') : t('admin.disable')}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-right">
                    <button
                      onClick={() => handleToggle(user.id, user.active)}
                      disabled={pendingId !== null}
                      aria-label={user.active ? t('admin.confirm_disable_user', user.username) : t('admin.confirm_enable_user', user.username)}
                      className="p-1 text-slate-400 hover:text-white transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {user.active ? <ShieldOff size={16} /> : <Shield size={16} />}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
