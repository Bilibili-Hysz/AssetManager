import { useEffect } from 'react';
import { useToast } from '../components/ui/Toast';
import { useI18n } from './useI18n';
import {
  ApiDegradationEvent,
  subscribeApiDegradation,
} from '../api/degradationBus';

function formatMessage(
  event: ApiDegradationEvent,
  translate: (key: string, ...args: Array<string | number>) => string,
): string {
  void translate;
  const base = event.kind === 'rate-limited'
    ? translate('error.rate_limited')
    : translate('error.server');
  if (event.kind === 'rate-limited'
      && event.retryAfterSeconds != null
      && event.retryAfterSeconds > 0) {
    return `${base} (≈${event.retryAfterSeconds}s)`;
  }
  return base;
}

/**
 * Mounts once inside <ToastProvider> to surface throttled client-level
 * degradation events. Re-renders only on toast dispatch.
 */
export function useApiDegradationToast(): void {
  const showToast = useToast().showToast;
  const { t } = useI18n();

  useEffect(() => subscribeApiDegradation(event => {
    try {
      showToast(formatMessage(event, t), 'error');
    } catch {
      // Toast unmount race: dropping one notification is acceptable.
    }
  }), [showToast, t]);
}
