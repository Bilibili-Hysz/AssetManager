import { Download } from 'lucide-react';
import { useCallback, useEffect, useRef, useState, type CSSProperties } from 'react';
import type { ShopApi } from '../../api/shop';
import { useI18n } from '../../hooks/useI18n';
import { useToast } from '../ui/Toast';

export interface BuyerDeliveryDownloadButtonProps {
  orderId: string | number;
  itemTitle: string;
  shop: ShopApi;
  label: string;
  loadingLabel: string;
  className?: string;
  style?: CSSProperties;
  iconSize?: number;
}

function createDeliveryRequestKey(orderId: string | number): string {
  const random = typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  return `buyer-delivery-${orderId}-${random}`.slice(0, 200);
}

function suggestedDownloadName(itemTitle: string): string {
  const safeTitle = itemTitle.replace(/[\\/:*?"<>|]/g, '_').trim() || 'asset';
  return `${safeTitle}.zip`;
}

export function BuyerDeliveryDownloadButton({
  orderId,
  itemTitle,
  shop,
  label,
  loadingLabel,
  className = 'storefront-button storefront-button-primary',
  style,
  iconSize = 16,
}: BuyerDeliveryDownloadButtonProps) {
  const { t } = useI18n();
  const { showToast } = useToast();
  const [downloading, setDownloading] = useState(false);
  const requestKeyRef = useRef<string | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    requestKeyRef.current = null;
  }, [orderId]);

  const download = useCallback(async () => {
    if (downloading) return;
    const requestKey = requestKeyRef.current ?? createDeliveryRequestKey(orderId);
    requestKeyRef.current = requestKey;
    setDownloading(true);
    try {
      const delivery = await shop.downloadOrderDelivery(orderId, requestKey);
      const objectUrl = URL.createObjectURL(delivery.blob);
      const anchor = document.createElement('a');
      anchor.href = objectUrl;
      anchor.download = delivery.filename ?? suggestedDownloadName(itemTitle);
      anchor.style.display = 'none';
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      // E5: delay the revoke so the browser has time to start the download — revoking
      // synchronously can abort the transfer in some browsers.
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
      requestKeyRef.current = null;
    } catch (error) {
      // E5: clear the request key on failure so a retry requests a fresh key. The server
      // treats the key as an idempotency token (the same key returns the same delivery),
      // so reusing a key after a failure could pin the retry to a stale/consumed request.
      requestKeyRef.current = null;
      if (mountedRef.current) {
        showToast(error instanceof Error ? error.message : t('commerce.product_not_found_description'), 'error');
      }
    } finally {
      if (mountedRef.current) setDownloading(false);
    }
  }, [downloading, itemTitle, orderId, shop, showToast, t]);

  return (
    <button
      type="button"
      className={className}
      style={style}
      disabled={downloading}
      aria-busy={downloading}
      onClick={() => void download()}
    >
      <Download size={iconSize} /> {downloading ? loadingLabel : label}
    </button>
  );
}
