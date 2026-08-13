import { useParams } from 'react-router-dom';
import { useState, useEffect, useMemo } from 'react';
import { Download, Lock, Folder, Eye } from 'lucide-react';
import { createApiClient } from '../api/client';
import { createSharesApi } from '../api/shares';
import { ApiError } from '../api/errors';
import { useI18n } from '../hooks/useI18n';
import { useTheme } from '../hooks/useTheme';
import { useToast } from '../components/ui/Toast';
import type { ShareInfoResponse } from '../types/api';

export default function ShareReceivePage() {
  const { shareId } = useParams<{ shareId: string }>();
  // Dedicated client on purpose: share verification answers 401 for a wrong
  // password or a revoked link. The global AuthContext client would treat
  // that as a session expiry and reset the visitor's identity, so this page
  // owns a client without an onUnauthorized handler.
  const api = useMemo(() => createApiClient(), []);
  const sharesApi = useMemo(() => createSharesApi(api), [api]);
  const { t } = useI18n();
  useTheme();
  const { showToast } = useToast();

  const [shareInfo, setShareInfo] = useState<ShareInfoResponse | null>(null);
  const [password, setPassword] = useState('');
  const [verified, setVerified] = useState(false);
  const [loading, setLoading] = useState(true);
  const [verifying, setVerifying] = useState(false);

  useEffect(() => {
    if (!shareId) return;
    let cancelled = false;
    setVerified(false);
    setShareInfo(null);
    setLoading(true);
    sharesApi.getInfo(shareId)
      .then(info => {
        if (cancelled) return;
        setShareInfo(info);
        // For password-protected shares: paths presence indicates backend returned
        // full share (authorized via scoped HttpOnly cookie). Sanitized preverify
        // response lacks paths, so verified stays false.
        if (info.has_password && info.paths) {
          setVerified(true);
        }
      })
      .catch(() => { if (!cancelled) showToast(t('share.failed_to_load'), 'error'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [shareId, sharesApi, showToast, t]);

  const handleVerify = async () => {
    if (!shareId || verifying) return;
    setVerifying(true);
    try {
      const res = await sharesApi.verifyPassword(shareId, password);
      setShareInfo(res.share);
      setVerified(true);
    } catch (err) {
      if (err instanceof ApiError && err.status === 429) {
        showToast(t('error.rate_limited'), 'error');
      } else if (err instanceof ApiError && err.status !== 401) {
        showToast(t('error.server'), 'error');
      } else {
        showToast(t('share.invalid_password'), 'error');
      }
    } finally {
      setVerifying(false);
    }
  };

  if (loading) {
    return (
      <div data-testid="share-loading" className="flex items-center justify-center h-screen bg-slate-950">
        <div className="skeleton h-8 w-48" />
      </div>
    );
  }

  if (!shareInfo) {
    return (
      <div className="flex items-center justify-center h-screen bg-slate-950">
        <p className="text-slate-400">{t('share.not_found')}</p>
      </div>
    );
  }

  if (shareInfo.expired) {
    return (
      <div className="flex items-center justify-center h-screen bg-slate-950">
        <p className="text-slate-400">{t('share.expired')}</p>
      </div>
    );
  }

  if (shareInfo.has_password && !verified) {
    return (
      <div className="flex flex-col items-center justify-center h-screen bg-slate-950 gap-6 p-8">
        <Lock size={48} className="text-slate-600" />
        <h1 className="text-xl font-semibold text-white">{t('share.password_required')}</h1>
        <form
          className="w-full max-w-xs space-y-3"
          onSubmit={e => {
            e.preventDefault();
            void handleVerify();
          }}
        >
          <input
            type="password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            aria-label={t('share.password')}
            placeholder={t('share.password')}
            className="w-full px-4 py-2.5 bg-slate-800 border border-slate-700/50 rounded-lg text-sm text-slate-200
              focus:outline-none focus:border-brand-500/50"
          />
          <button
            type="submit"
            disabled={verifying}
            className="w-full py-2.5 text-sm text-white bg-brand-500 hover:bg-brand-600 disabled:opacity-60 rounded-lg transition-colors"
          >
            {t('share.verify_btn')}
          </button>
        </form>
      </div>
    );
  }

  const paths = shareInfo.paths ?? [];
  return (
    <div className="min-h-screen bg-slate-950 p-6">
      <h1 className="text-2xl font-bold text-white mb-6">{t('share.title')}</h1>
      {paths.length === 0 ? (
        <p className="text-slate-400">{t('share.no_files')}</p>
      ) : (
        paths.map(path => (
          <div key={path} className="flex items-center gap-3 px-4 py-2.5 rounded-lg hover:bg-slate-800/30">
            <Folder size={18} className="text-amber-400" />
            <span className="text-sm text-slate-200 flex-1 truncate">{path}</span>
            {shareInfo.allow_preview && (
              <a
                href={sharesApi.getPreviewUrl(shareId!, path)}
                aria-label={t('share.preview')}
                className="p-2 text-slate-400 hover:text-white transition-colors"
              >
                <Eye size={16} />
              </a>
            )}
            <a
              href={sharesApi.getDownloadUrl(shareId!, path)}
              aria-label={t('share.download')}
              className="p-2 text-slate-400 hover:text-white transition-colors"
            >
              <Download size={16} />
            </a>
          </div>
        ))
      )}
    </div>
  );
}
