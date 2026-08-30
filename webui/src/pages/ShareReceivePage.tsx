import { useParams } from 'react-router-dom';
import { useState, useEffect } from 'react';
import { Download, Lock, Folder, Eye } from 'lucide-react';
import { ApiError } from '../api/errors';
import { useI18n } from '../hooks/useI18n';
import { useTheme } from '../hooks/useTheme';
import { usePublicShareApi } from '../hooks/usePageApis';
import { useToast } from '../components/ui/Toast';
import type { ShareInfoResponse } from '../types/api';

type Translate = (key: string, ...args: (string | number)[]) => string;

function formatExpiryText(hours: number, t: Translate, lang: string): string {
  if (hours > 24) {
    // The API rounds to 0.1h, so the projected calendar date is accurate to a
    // few minutes — enough for a day-level display.
    const locale = lang === 'zh' ? 'zh-CN' : lang === 'ja' ? 'ja-JP' : 'en-US';
    const expiresAt = new Date(Date.now() + hours * 3_600_000);
    return t('share.expires_on', expiresAt.toLocaleDateString(locale));
  }
  if (hours >= 1) {
    const shown = hours % 1 === 0 ? String(Math.round(hours)) : hours.toFixed(1);
    return t('share.expires_in_hours', shown);
  }
  return t('share.expires_in_minutes', Math.max(1, Math.round(hours * 60)));
}

export default function ShareReceivePage() {
  const { shareId } = useParams<{ shareId: string }>();
  // Dedicated client on purpose: share verification answers 401 for a wrong
  // password or a revoked link. The global AuthContext client would treat
  // that as a session expiry and reset the visitor's identity, so this page
  // uses a client without an onUnauthorized handler (usePublicShareApi owns
  // that dedicated client).
  const sharesApi = usePublicShareApi();
  const { t, lang } = useI18n();
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
      <div data-testid="share-loading" className="flex items-center justify-center min-h-[100dvh] bg-slate-950">
        <div className="skeleton h-8 w-48" />
      </div>
    );
  }

  if (!shareInfo) {
    return (
      <div className="flex items-center justify-center min-h-[100dvh] bg-slate-950">
        <p className="text-slate-400">{t('share.not_found')}</p>
      </div>
    );
  }

  if (shareInfo.expired) {
    return (
      <div className="flex items-center justify-center min-h-[100dvh] bg-slate-950">
        <p className="text-slate-400">{t('share.expired')}</p>
      </div>
    );
  }

  if (shareInfo.has_password && !verified) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[100dvh] bg-slate-950 gap-6 p-8">
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
            className="w-full py-2.5 text-sm text-white bg-brand-600 hover:bg-brand-700 disabled:opacity-60 rounded-lg transition-colors"
          >
            {t('share.verify_btn')}
          </button>
        </form>
      </div>
    );
  }

  const paths = shareInfo.paths ?? [];
  // The backend applies max_downloads as a hard lifetime cap
  // (domain/share.py is_download_limit_reached) with no reset cycle, so the
  // exhausted copy stays neutral. Remaining 1 gets the warning color.
  const quotaRemaining = shareInfo.max_downloads != null
    ? Math.max(0, shareInfo.max_downloads - (shareInfo.download_count ?? 0))
    : null;
  const quotaClass = quotaRemaining == null || quotaRemaining > 1
    ? 'border-slate-600/60 bg-slate-800/60 text-slate-300'
    : quotaRemaining === 1
      ? 'border-amber-500/40 bg-amber-500/10 text-amber-400'
      : 'border-red-500/40 bg-red-500/10 text-red-400';
  return (
    <div className="min-h-[100dvh] bg-slate-950 p-6">
      <h1 className="text-2xl font-bold text-white mb-2">{t('share.title')}</h1>
      {(quotaRemaining != null || shareInfo.expires_in_hours != null) && (
        <div className="flex flex-wrap items-center gap-2 mb-6">
          {quotaRemaining != null && (
            <span
              data-testid="share-quota"
              role="status"
              className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-medium ${quotaClass}`}
            >
              {quotaRemaining > 0
                ? t('share.quota_remaining', quotaRemaining, shareInfo.max_downloads ?? 0)
                : t('share.quota_exhausted')}
            </span>
          )}
          {shareInfo.expires_in_hours != null && (
            <span
              data-testid="share-expires"
              role="status"
              className="inline-flex items-center rounded-full border border-slate-600/60 bg-slate-800/60 px-3 py-1 text-xs font-medium text-slate-300"
            >
              {formatExpiryText(shareInfo.expires_in_hours, t, lang)}
            </span>
          )}
        </div>
      )}
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
