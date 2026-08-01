import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { Plus, X } from 'lucide-react';
import { useAuth } from '../../hooks/useAuth';
import { createUsersApi } from '../../api/users';
import type { InviteCode } from '../../types/api';
import { useI18n } from '../../hooks/useI18n';
import { useToast } from '../ui/Toast';
import { useInvalidation } from '../../hooks/useInvalidation';

export function InviteManagement() {
  const { api, identityGeneration } = useAuth();
  const usersApi = useMemo(() => createUsersApi(api), [api]);
  const { t } = useI18n();
  const { showToast } = useToast();
  const [invites, setInvites] = useState<InviteCode[]>([]);
  const requestGeneration = useRef(0);
  const identityGenerationRef = useRef(identityGeneration);

  const refreshInvites = useCallback(() => {
    const generation = ++requestGeneration.current;
    return usersApi.listInvites().then(res => {
      if (generation === requestGeneration.current) setInvites(res.invites);
    });
  }, [usersApi]);

  useEffect(() => {
    refreshInvites().catch(() => {});
    return () => { requestGeneration.current += 1; };
  }, [refreshInvites]);
  useEffect(() => {
    if (identityGenerationRef.current === identityGeneration) return;
    identityGenerationRef.current = identityGeneration;
    requestGeneration.current += 1;
    setInvites([]);
    refreshInvites().catch(() => {});
  }, [identityGeneration, refreshInvites]);
  useInvalidation(['users'], refreshInvites);

  const handleCreate = async () => {
    try {
      await usersApi.createInvite();
      await refreshInvites();
      showToast(t('admin.invite_created'), 'success');
    } catch {}
  };

  const handleRevoke = async (code: string) => {
    try {
      await usersApi.revokeInvite(code);
      await refreshInvites();
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
                {invite.revoked ? t('admin.revoke') : invite.used_by ? t('admin.invite_used') : t('admin.invite_active')}
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
