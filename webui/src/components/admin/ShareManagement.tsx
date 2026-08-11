import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { Trash2, Link as LinkIcon } from 'lucide-react';
import { useAuth } from '../../hooks/useAuth';
import { createSharesApi } from '../../api/shares';
import type { ShareLink } from '../../types/api';
import { useI18n } from '../../hooks/useI18n';
import { useToast } from '../ui/Toast';
import { useInvalidation } from '../../hooks/useInvalidation';

// NOTE: this admin panel is not yet mounted on any route — wiring the Admin section
// into the router is a later task (see D2 in the component backlog).

export function ShareManagement() {
  const { api, identityGeneration } = useAuth();
  const sharesApi = useMemo(() => createSharesApi(api), [api]);
  const { t } = useI18n();
  const { showToast } = useToast();
  const [shares, setShares] = useState<ShareLink[]>([]);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const requestGeneration = useRef(0);
  const identityGenerationRef = useRef(identityGeneration);

  const refreshShares = useCallback(() => {
    const generation = ++requestGeneration.current;
    return sharesApi.list().then(res => {
      if (generation === requestGeneration.current) setShares(res.shares);
    });
  }, [sharesApi]);

  useEffect(() => {
    refreshShares().catch(() => {});
    return () => { requestGeneration.current += 1; };
  }, [refreshShares]);
  useEffect(() => {
    if (identityGenerationRef.current === identityGeneration) return;
    identityGenerationRef.current = identityGeneration;
    requestGeneration.current += 1;
    setShares([]);
    refreshShares().catch(() => {});
  }, [identityGeneration, refreshShares]);
  useInvalidation(['shares'], refreshShares);

  const handleDelete = async (id: string) => {
    // E3: require explicit confirmation before deleting a share link.
    if (!window.confirm(t('admin.confirm_delete_share', id))) return;
    setPendingId(id);
    try {
      await sharesApi.delete(id);
      await refreshShares();
    } catch {
      showToast(t('admin.delete_share_failed'), 'error');
    } finally {
      setPendingId(null);
    }
  };

  return (
    <div>
      <h3 className="text-lg font-semibold text-white mb-4">{t('admin.shares')}</h3>
      {shares.length === 0 ? (
        <p className="text-sm text-slate-500">{t('share.no_shares')}</p>
      ) : (
        <div className="space-y-2">
          {shares.map(share => (
            <div key={share.id} className="flex items-center gap-3 px-4 py-2.5 rounded-lg bg-slate-800/30 border border-slate-700/50">
              <LinkIcon size={16} className="text-slate-500" />
              <div className="flex-1 min-w-0">
                <p className="text-sm text-slate-200 truncate">{share.url}</p>
                <p className="text-xs text-slate-500">{t('share.downloads', share.download_count, share.max_downloads ?? '∞')}</p>
              </div>
              <button aria-label={`${t('action.delete')} ${share.url}`} onClick={() => handleDelete(share.id)} disabled={pendingId !== null} className="p-1 text-slate-400 hover:text-red-400 transition-colors disabled:opacity-50 disabled:cursor-not-allowed">
                <Trash2 size={14} aria-hidden="true" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
