import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { Shield, ShieldOff } from 'lucide-react';
import { useAuth } from '../../hooks/useAuth';
import { createUsersApi } from '../../api/users';
import type { User } from '../../types/api';
import { useI18n } from '../../hooks/useI18n';
import { useInvalidation } from '../../hooks/useInvalidation';

export function UserManagement() {
  const { api, identityGeneration } = useAuth();
  const usersApi = useMemo(() => createUsersApi(api), [api]);
  const { t } = useI18n();
  const [users, setUsers] = useState<User[]>([]);
  const requestGeneration = useRef(0);
  const identityGenerationRef = useRef(identityGeneration);

  const refreshUsers = useCallback(() => {
    const generation = ++requestGeneration.current;
    return usersApi.list().then(res => {
      if (generation === requestGeneration.current) setUsers(res.users);
    });
  }, [usersApi]);

  useEffect(() => {
    refreshUsers().catch(() => {});
    return () => { requestGeneration.current += 1; };
  }, [refreshUsers]);
  useEffect(() => {
    if (identityGenerationRef.current === identityGeneration) return;
    identityGenerationRef.current = identityGeneration;
    requestGeneration.current += 1;
    setUsers([]);
    refreshUsers().catch(() => {});
  }, [identityGeneration, refreshUsers]);
  useInvalidation(['users'], refreshUsers);

  const handleToggle = async (id: number, current: boolean) => {
    try {
      await usersApi.toggleUser(id, !current);
      await refreshUsers();
    } catch {}
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
                <th className="text-right text-xs text-slate-500 font-medium px-4 py-2">{t('action')}</th>
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
                      className="p-1 text-slate-400 hover:text-white transition-colors"
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
