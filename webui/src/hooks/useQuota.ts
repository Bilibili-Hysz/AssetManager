import { useCallback, useEffect, useRef, useState } from 'react';
import { useAuth } from './useAuth';
import { useToast } from '../components/ui/Toast';
import { useI18n } from './useI18n';
import type { QuotaInfo } from '../types/api';

/**
 * Provides the optional download quota and a guard for download actions.
 * Quota failures are deliberately fail-open because the endpoint is optional.
 */
export function useQuota() {
  const { systemApi } = useAuth();
  const { t } = useI18n();
  const { showToast } = useToast();
  const [quota, setQuota] = useState<QuotaInfo | null>(null);
  const quotaRef = useRef<QuotaInfo | null>(null);
  const generationRef = useRef(0);
  const mountedRef = useRef(true);
  const activeApiRef = useRef(systemApi);

  useEffect(() => {
    mountedRef.current = true;
    activeApiRef.current = systemApi;
    generationRef.current += 1;
    quotaRef.current = null;
    setQuota(null);

    return () => {
      mountedRef.current = false;
      generationRef.current += 1;
    };
  }, [systemApi]);

  const refresh = useCallback(async (): Promise<void> => {
    const api = systemApi;
    const generation = generationRef.current;
    try {
      const info = await api.getQuota();
      if (!mountedRef.current || generation !== generationRef.current || activeApiRef.current !== api) return;
      quotaRef.current = info;
      setQuota(info);
    } catch {
      // Quota is optional: retain the last known value and fail open.
    }
  }, [systemApi]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const guardDownload = useCallback(async (): Promise<boolean> => {
    const api = systemApi;
    const generation = generationRef.current;
    let current = quotaRef.current;

    if (!current) {
      try {
        current = await api.getQuota();
        if (mountedRef.current && generation === generationRef.current && activeApiRef.current === api) {
          quotaRef.current = current;
          setQuota(current);
        }
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
  }, [showToast, systemApi, t]);

  return { quota, refresh, guardDownload };
}
