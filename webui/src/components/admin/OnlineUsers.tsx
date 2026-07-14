import { useState, useEffect, useMemo } from 'react';
import { useAuth } from '../../hooks/useAuth';
import { createUsersApi } from '../../api/users';
import { useI18n } from '../../hooks/useI18n';
import type { OnlineUsersResponse } from '../../types/api';

export function OnlineUsers() {
  const { api } = useAuth();
  const usersApi = useMemo(() => createUsersApi(api), [api]);
  const { t } = useI18n();
  const [users, setUsers] = useState<OnlineUsersResponse['users']>([]);

  useEffect(() => {
    usersApi.getOnlineUsers().then(res => setUsers(res.users)).catch(() => {});
  }, [usersApi]);

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
