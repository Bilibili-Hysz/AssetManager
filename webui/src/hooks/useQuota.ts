import { useCallback, useRef } from 'react';
import { useAuth } from './useAuth';
import { useToast } from '../components/ui/Toast';
import { useI18n } from './useI18n';
import { useCachedQuery } from './useCachedQuery';
import type { QuotaInfo } from '../types/api';

/**
 * Provides the optional download quota and a guard for download actions.
 * Quota failures are deliberately fail-open because the endpoint is optional:
 * the cached entry keeps the last known value on a failed refresh, and
 * guardDownload re-checks directly when nothing was loaded yet.
 */
export function useQuota() {
  const { systemApi } = useAuth();
  const { t } = useI18n();
  const { showToast } = useToast();

  const { data, refresh, setData } = useCachedQuery<QuotaInfo | null>({
    key: ['quota'],
    queryFn: () => systemApi.getQuota(),
  });

  const quota = data ?? null;
  // Live view for guardDownload, which runs outside React's render cycle.
  const quotaRef = useRef(quota);
  quotaRef.current = quota;

  const guardDownload = useCallback(async (): Promise<boolean> => {
    let current = quotaRef.current;
    if (!current) {
      try {
        current = await systemApi.getQuota();
        setData(() => current);
      } catch {
        return true;
      }
    }

    if (!current.enabled) return true;
    if (current.remaining !== null && current.remaining <= 0) {
      showToast(t('quota.exhausted'), 'error');
      return false;
    }
    if (current.remaining !== null && current.remaining <= 2) {
      showToast(t('quota.low', current.remaining), 'info');
    }
    return true;
  }, [setData, showToast, systemApi, t]);

  return { quota, refresh, guardDownload };
}
