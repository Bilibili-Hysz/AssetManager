import { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import { useAuth } from '../../hooks/useAuth';
import { createUsersApi } from '../../api/users';
import { useI18n } from '../../hooks/useI18n';
import type { OnlineUsersResponse } from '../../types/api';
import { useInvalidation } from '../../hooks/useInvalidation';

export function OnlineUsers() {
  const { api } = useAuth();
  const usersApi = useMemo(() => createUsersApi(api), [api]);
  const { t } = useI18n();
  const [users, setUsers] = useState<OnlineUsersResponse['users']>([]);
  const requestGeneration = useRef(0);
  const mounted = useRef(true);

  const refreshUsers = useCallback(() => {
    const generation = ++requestGeneration.current;
    usersApi.getOnlineUsers().then(res => {
      if (mounted.current && generation === requestGeneration.current) setUsers(res.users);
    }).catch(() => {});
  }, [usersApi]);
  useEffect(() => {
    mounted.current = true;
    refreshUsers();
    return () => { mounted.current = false; requestGeneration.current += 1; };
  }, [refreshUsers]);
  useInvalidation(['users', 'shares', 'stats'], refreshUsers);

  return (
    <div>
      <h3 className="text-lg font-semibold text-white mb-4">{t('admin.online')}</h3>
      {users.length === 0 ? (
        <p className="text-sm text-slate-500">{t('admin.no_online')}</p>
      ) : (
        <div className="space-y-2">
          {users.map((u, i) => (
            <div key={i} className="flex items-center gap-3 px-4 py-2.5 rounded-lg bg-slate-800/30 border border-slate-700/50">
              <div className="w-2 h-2 rounded-full bg-emerald-500" />
              <span className="text-sm text-slate-200 flex-1">{u.username}</span>
              <span className="text-xs text-slate-500">{u.ip}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
