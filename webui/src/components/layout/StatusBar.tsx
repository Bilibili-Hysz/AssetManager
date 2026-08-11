import { useCallback, useEffect, useRef, useState } from 'react';
import { useAuth } from '../../hooks/useAuth';
import { useInvalidation } from '../../hooks/useInvalidation';
import { useRealtimeContext } from '../../stores/RealtimeContext';
import { useI18n } from '../../hooks/useI18n';
import { useQuota } from '../../hooks/useQuota';
import type { StatsResponse } from '../../types/api';

interface StatusBarProps {
  sidebarOpen: boolean;
  infoOpen: boolean;
}

export function StatusBar(_props: StatusBarProps) {
  const { systemApi } = useAuth();
  const { t } = useI18n();
  const { quota } = useQuota();
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const { status: wsStatus } = useRealtimeContext();
  const mountedRef = useRef(false);
  const generationRef = useRef(0);
  const load = useCallback(() => {
    const generation = ++generationRef.current;
    systemApi.getStats().then(stats => {
      if (mountedRef.current && generation === generationRef.current) setStats(stats);
    }).catch(() => {});
  }, [systemApi]);

  useInvalidation(['stats'], load);

  useEffect(() => {
    mountedRef.current = true;
    load();
    const timer = setInterval(load, 10000);
    return () => {
      mountedRef.current = false;
      clearInterval(timer);
    };
  }, [load]);

  return (
    <div
      className="h-7 flex items-center text-[10px] px-3 flex-shrink-0 transition-theme"
      style={{
        borderTop: '1px solid var(--color-border)',
        backgroundColor: 'var(--color-surface)',
        color: 'var(--color-text-muted)',
      }}
    >
      <div className="flex items-center gap-3 flex-1 min-w-0">
        {stats && (
          <>
            <span>{t('status.connections', stats.connections)}</span>
            <span style={{ color: 'var(--color-text-muted)' }}>·</span>
            <span>{t('status.requests', stats.requests)}</span>
            <span style={{ color: 'var(--color-text-muted)' }}>·</span>
            <span>{stats.bytes_transferred_fmt ?? 'Unavailable'}</span>
          </>
        )}
        {quota && quota.enabled && quota.remaining !== null && (
          <>
            {stats && <span style={{ color: 'var(--color-text-muted)' }}>·</span>}
            <span style={{ color: quota.remaining > 0 ? 'var(--color-text-muted)' : 'var(--color-danger-text)' }}>
              {t('quota.status', quota.remaining)}
            </span>
          </>
        )}
      </div>
      <div className="flex items-center gap-3">
        <span className="flex items-center gap-1" role="status" aria-live="polite">
          <span
            className="w-1.5 h-1.5 rounded-full"
            style={{
              backgroundColor: wsStatus === 'connected' ? 'var(--color-success)' :
                wsStatus === 'connecting' ? 'var(--color-warning)' : 'var(--color-text-muted)',
            }}
          />
          {wsStatus === 'connected' ? t('status.connected') : wsStatus === 'connecting' ? t('status.reconnecting') : t('status.disconnected')}
        </span>
        {stats && stats.uptime > 0 && (
          <span>{t('status.uptime', `${Math.floor(stats.uptime / 3600)}h ${Math.floor((stats.uptime % 3600) / 60)}m`)}</span>
        )}
      </div>
    </div>
  );
}
