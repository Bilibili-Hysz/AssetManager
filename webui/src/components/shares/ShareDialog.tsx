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
    setCreating(true);
    try {
      const res = await sharesApi.create({
        paths,
        password: password || undefined,
        expires_hours: expiresHours > 0 ? expiresHours : undefined,
        max_downloads: maxDownloads > 0 ? maxDownloads : undefined,
        allow_preview: allowPreview,
      });
      setShareUrl(res.url!);
      showToast('Share link created!', 'success');
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to create share', 'error');
    } finally {
      setCreating(false);
    }
  };

  const handleCopy = () => {
    navigator.clipboard.writeText(shareUrl).catch(() => {});
    showToast(t('action.copied'), 'success');
  };

  return (
    <Modal open={open} onClose={onClose} title={t('share.create_title')} returnFocusTo={returnFocusTo}>
      {shareUrl ? (
        <div className="space-y-4">
          <p className="text-sm text-slate-300">Share link created!</p>
          <div className="flex items-center gap-2 p-3 bg-slate-800 rounded-lg border border-slate-700/50">
            <input
              type="text"
              value={shareUrl}
              readOnly
              className="flex-1 bg-transparent text-sm text-slate-200 outline-none"
            />
            <button
              onClick={handleCopy}
              className="px-3 py-1 text-xs text-white bg-brand-500 hover:bg-brand-600 rounded-md transition-colors"
            >
              {t('action.copy')}
            </button>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <div>
            <label className="block text-xs text-slate-500 mb-1">{t('share.password')}</label>
            <input
              type="text"
              value={password}
              onChange={e => setPassword(e.target.value)}
              className="w-full px-3 py-2 bg-slate-800 border border-slate-700/50 rounded-lg text-sm text-slate-200
                focus:outline-none focus:border-brand-500/50"
              placeholder="Leave empty for no password"
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs text-slate-500 mb-1">{t('share.expires')}</label>
              <input
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
              <label className="block text-xs text-slate-500 mb-1">{t('share.max_downloads')}</label>
              <input
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
            onClick={handleCreate}
            disabled={creating}
            className="w-full py-2 text-sm text-white bg-brand-500 hover:bg-brand-600 disabled:opacity-50 rounded-lg transition-colors"
          >
            {creating ? t('browse.loading') : t('share.create_btn')}
          </button>
        </div>
      )}
    </Modal>
  );
}