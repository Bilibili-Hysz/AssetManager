import { useParams } from 'react-router-dom';
import { useState, useEffect } from 'react';
import { Download, Lock, Folder } from 'lucide-react';
import { createApiClient } from '../api/client';
import { createSharesApi } from '../api/shares';
import { useI18n } from '../hooks/useI18n';
import { useToast } from '../components/ui/Toast';
import type { ShareInfoResponse } from '../types/api';

export default function ShareReceivePage() {
  const { shareId } = useParams<{ shareId: string }>();
  const api = createApiClient();
  const sharesApi = createSharesApi(api);
  const { t } = useI18n();
  const { showToast } = useToast();

  const [shareInfo, setShareInfo] = useState<ShareInfoResponse | null>(null);
  const [password, setPassword] = useState('');
  const [token, setToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!shareId) return;
    setLoading(true);
    sharesApi.getInfo(shareId)
      .then(setShareInfo)
      .catch(() => showToast('Failed to load share', 'error'))
      .finally(() => setLoading(false));
  }, [shareId]);

  const handleVerify = async () => {
    try {
      const res = await sharesApi.verifyPassword(shareId!, password);
      setToken(res.token);
    } catch {
      showToast('Invalid password', 'error');
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen bg-slate-950">
        <div className="skeleton h-8 w-48" />
      </div>
    );
  }

  if (!shareInfo) {
    return (
      <div className="flex items-center justify-center h-screen bg-slate-950">
        <p className="text-slate-400">Share not found</p>
      </div>
    );
  }

  if (shareInfo.has_password && !token) {
    return (
      <div className="flex flex-col items-center justify-center h-screen bg-slate-950 gap-6 p-8">
        <Lock size={48} className="text-slate-600" />
        <h1 className="text-xl font-semibold text-white">{t('share.password_required')}</h1>
        <div className="w-full max-w-xs space-y-3">
          <input
            type="password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            placeholder={t('share.password')}
            className="w-full px-4 py-2.5 bg-slate-800 border border-slate-700/50 rounded-lg text-sm text-slate-200
              focus:outline-none focus:border-brand-500/50"
          />
          <button
            onClick={handleVerify}
            className="w-full py-2.5 text-sm text-white bg-brand-500 hover:bg-brand-600 rounded-lg transition-colors"
          >
            {t('share.verify_btn')}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-950 p-6">
      <h1 className="text-2xl font-bold text-white mb-6">Shared Files</h1>
      {shareInfo.paths?.map(path => (
        <div key={path} className="flex items-center gap-3 px-4 py-2.5 rounded-lg hover:bg-slate-800/30">
          <Folder size={18} className="text-amber-400" />
          <span className="text-sm text-slate-200 flex-1">{path}</span>
          <a
            href={sharesApi.getDownloadUrl(shareId!, path)}
            className="p-2 text-slate-400 hover:text-white transition-colors"
          >
            <Download size={16} />
          </a>
        </div>
      ))}
    </div>
  );
}