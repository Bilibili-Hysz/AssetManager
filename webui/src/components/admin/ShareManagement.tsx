import { useState, useEffect, useMemo } from 'react';
import { Trash2, Link as LinkIcon } from 'lucide-react';
import { useAuth } from '../../hooks/useAuth';
import { createSharesApi } from '../../api/shares';
import type { ShareLink } from '../../types/api';
import { useI18n } from '../../hooks/useI18n';

export function ShareManagement() {
  const { api } = useAuth();
  const sharesApi = useMemo(() => createSharesApi(api), [api]);
  const { t } = useI18n();
  const [shares, setShares] = useState<ShareLink[]>([]);

  useEffect(() => {
    sharesApi.list().then(res => setShares(res.shares)).catch(() => {});
  }, [sharesApi]);

  const handleDelete = async (id: string) => {
    try {
      await sharesApi.delete(id);
      setShares(prev => prev.filter(s => s.id !== id));
    } catch {}
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
              <button aria-label={`${t('action.delete')} ${share.url}`} onClick={() => handleDelete(share.id)} className="p-1 text-slate-400 hover:text-red-400 transition-colors">
                <Trash2 size={14} aria-hidden="true" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
