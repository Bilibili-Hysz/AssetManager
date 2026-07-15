import { useState, useEffect, useMemo } from 'react';
import { Plus, X } from 'lucide-react';
import { useAuth } from '../../hooks/useAuth';
import { createUsersApi } from '../../api/users';
import type { InviteCode } from '../../types/api';
import { useI18n } from '../../hooks/useI18n';
import { useToast } from '../ui/Toast';

export function InviteManagement() {
  const { api } = useAuth();
  const usersApi = useMemo(() => createUsersApi(api), [api]);
  const { t } = useI18n();
  const { showToast } = useToast();
  const [invites, setInvites] = useState<InviteCode[]>([]);

  useEffect(() => {
    usersApi.listInvites().then(res => setInvites(res.invites)).catch(() => {});
  }, [usersApi]);

  const handleCreate = async () => {
    try {
      const res = await usersApi.createInvite();
      setInvites(prev => [{ code: res.code, created_at: new Date().toISOString(), revoked: false }, ...prev]);
      showToast('Invite code created!', 'success');
    } catch {}
  };

  const handleRevoke = async (code: string) => {
    try {
      await usersApi.revokeInvite(code);
      setInvites(prev => prev.map(i => i.code === code ? { ...i, revoked: true } : i));
    } catch {}
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold text-white">{t('admin.invites')}</h3>
        <button
          onClick={handleCreate}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-white bg-brand-500 hover:bg-brand-600 rounded-md transition-colors"
        >
          <Plus size={14} /> {t('admin.generate_invite')}
        </button>
      </div>
      {invites.length === 0 ? (
        <p className="text-sm text-slate-500">{t('admin.no_invites')}</p>
      ) : (
        <div className="space-y-2">
          {invites.map(invite => (
            <div key={invite.code} className="flex items-center gap-3 px-4 py-2.5 rounded-lg bg-slate-800/30 border border-slate-700/50">
              <code className="flex-1 text-sm text-slate-200 font-mono">{invite.code}</code>
              <span className={`text-xs ${invite.revoked ? 'text-red-400' : invite.used_by ? 'text-slate-500' : 'text-emerald-400'}`}>
                {invite.revoked ? t('admin.revoke') : invite.used_by ? 'Used' : 'Active'}
              </span>
              {!invite.revoked && !invite.used_by && (
                <button aria-label={`${t('admin.revoke')} ${invite.code}`} onClick={() => handleRevoke(invite.code)} className="p-1 text-slate-400 hover:text-white transition-colors">
                  <X size={14} aria-hidden="true" />
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
