import { useState } from 'react';
import { useAuth } from '../../hooks/useAuth';
import { createSharesApi } from '../../api/shares';
import { Modal } from '../ui/Modal';
import { useI18n } from '../../hooks/useI18n';
import { useToast } from '../ui/Toast';

interface ShareDialogProps {
  open: boolean;
  onClose: () => void;
  paths: string[];
  returnFocusTo?: HTMLElement | null;
}

export function ShareDialog({ open, onClose, paths, returnFocusTo }: ShareDialogProps) {
  const { api } = useAuth();
  const sharesApi = createSharesApi(api);
  const { t } = useI18n();
  const { showToast } = useToast();

  const [password, setPassword] = useState('');
  const [expiresHours, setExpiresHours] = useState(24);
  const [maxDownloads, setMaxDownloads] = useState(0);
  const [allowPreview, setAllowPreview] = useState(true);
  const [creating, setCreating] = useState(false);
  const [shareUrl, setShareUrl] = useState('');

  const handleCreate = async () => {
    // E6: the number inputs only constrain the spinners, not typed values — clamp to the
    // documented ranges on submit so a stale/out-of-range value never reaches the server.
    const expires = Number.isFinite(expiresHours) ? Math.min(8760, Math.max(0, Math.round(expiresHours))) : 0;
    const downloads = Number.isFinite(maxDownloads) ? Math.min(10000, Math.max(0, Math.round(maxDownloads))) : 0;
    setExpiresHours(expires);
    setMaxDownloads(downloads);
    setCreating(true);
    try {
      const res = await sharesApi.create({
        paths,
        password: password || undefined,
        expires_hours: expires > 0 ? expires : undefined,
        max_downloads: downloads > 0 ? downloads : undefined,
        allow_preview: allowPreview,
      });
      if (!res.url) {
        // share.url_missing is asserted as a key through the key-pass-through
        // t() mock in ShareDialog.test.tsx.
        showToast(t('share.url_missing'), 'error');
        return;
      }
      setShareUrl(res.url);
      showToast(t('share.link_created'), 'success');
    } catch (err) {
      showToast(err instanceof Error ? err.message : t('share.create_failed'), 'error');
    } finally {
      setCreating(false);
    }
  };

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(shareUrl);
      showToast(t('action.copied'), 'success');
    } catch {
      // share.copy_failed is asserted as a key through the key-pass-through
      // t() mock in ShareDialog.test.tsx.
      showToast(t('share.copy_failed'), 'error');
    }
  };

  return (
    <Modal open={open} onClose={onClose} title={t('share.create_title')} returnFocusTo={returnFocusTo}>
      {shareUrl ? (
        <div className="space-y-4">
          <p className="text-sm text-slate-300">{t('share.link_created')}</p>
          <div className="flex items-center gap-2 p-3 bg-slate-800 rounded-lg border border-slate-700/50">
            <input
              type="text"
              value={shareUrl}
              readOnly
              aria-label={t('share.link_created')}
              className="flex-1 bg-transparent text-sm text-slate-200 outline-none"
            />
            <button
              type="button"
              onClick={handleCopy}
              aria-label={t('action.copy')}
              className="px-3 py-1 text-xs text-white bg-brand-600 hover:bg-brand-700 rounded-md transition-colors"
            >
              {t('action.copy')}
            </button>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <div>
            <label htmlFor="share-password" className="block text-xs text-slate-500 mb-1">{t('share.password')}</label>
            <input
              id="share-password"
              type="text"
              value={password}
              onChange={e => setPassword(e.target.value)}
              className="w-full px-3 py-2 bg-slate-800 border border-slate-700/50 rounded-lg text-sm text-slate-200
                focus:outline-none focus:border-brand-500/50"
              placeholder={t('share.password_placeholder')}
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label htmlFor="share-expires" className="block text-xs text-slate-500 mb-1">{t('share.expires')}</label>
              <input
                id="share-expires"
                type="number"
                value={expiresHours}
                onChange={e => setExpiresHours(Number(e.target.value))}
                min={0}
                max={8760}
                className="w-full px-3 py-2 bg-slate-800 border border-slate-700/50 rounded-lg text-sm text-slate-200
                  focus:outline-none focus:border-brand-500/50"
              />
            </div>
            <div>
              <label htmlFor="share-max-downloads" className="block text-xs text-slate-500 mb-1">{t('share.max_downloads')}</label>
              <input
                id="share-max-downloads"
                type="number"
                value={maxDownloads}
                onChange={e => setMaxDownloads(Number(e.target.value))}
                min={0}
                max={10000}
                className="w-full px-3 py-2 bg-slate-800 border border-slate-700/50 rounded-lg text-sm text-slate-200
                  focus:outline-none focus:border-brand-500/50"
              />
            </div>
          </div>

          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={allowPreview}
              onChange={e => setAllowPreview(e.target.checked)}
              className="rounded border-slate-600"
            />
            <span className="text-sm text-slate-300">{t('share.allow_preview')}</span>
          </label>

          <button
            type="button"
            onClick={handleCreate}
            disabled={creating}
            className="w-full py-2 text-sm text-white bg-brand-600 hover:bg-brand-700 disabled:opacity-50 rounded-lg transition-colors"
          >
            {creating ? t('browse.loading') : t('share.create_btn')}
          </button>
        </div>
      )}
    </Modal>
  );
}
