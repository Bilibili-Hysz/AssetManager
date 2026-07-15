import { useEffect, useState } from 'react';
import { useAuth } from '../../hooks/useAuth';
import { useWebSocket } from '../../hooks/useWebSocket';
import { useI18n } from '../../hooks/useI18n';
import type { StatsResponse } from '../../types/api';

interface StatusBarProps {
  sidebarOpen: boolean;
  infoOpen: boolean;
}

export function StatusBar(_props: StatusBarProps) {
  const { systemApi, user } = useAuth();
  const { t } = useI18n();
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const { status: wsStatus } = useWebSocket({ enabled: Boolean(user) });

  useEffect(() => {
    let disposed = false;
    const load = () => {
      systemApi.getStats().then(stats => {
        if (!disposed) setStats(stats);
      }).catch(() => {});
    };
    load();
    const timer = setInterval(load, 10000);
    return () => {
      disposed = true;
      clearInterval(timer);
    };
  }, [systemApi]);

  return (
    <div className="h-7 flex items-center text-[10px] text-slate-500 px-3 border-t border-slate-700/50 bg-slate-900/80 flex-shrink-0">
      <div className="flex items-center gap-3 flex-1 min-w-0">
        {stats && (
          <>
            <span>{t('status.connections', stats.connections)}</span>
            <span>·</span>
            <span>{t('status.requests', stats.requests)}</span>
            <span>·</span>
            <span>{stats.bytes_transferred_fmt}</span>
          </>
        )}
      </div>
      <div className="flex items-center gap-3">
        <span className="flex items-center gap-1" role="status" aria-live="polite">
          <span className={`w-1.5 h-1.5 rounded-full ${wsStatus === 'connected' ? 'bg-green-500' : wsStatus === 'connecting' ? 'bg-yellow-500' : 'bg-slate-600'}`} />
          {wsStatus === 'connected' ? t('status.connected') : wsStatus === 'connecting' ? t('status.reconnecting') : t('status.disconnected')}
        </span>
        {stats && stats.uptime > 0 && (
          <span>{t('status.uptime', `${Math.floor(stats.uptime / 3600)}h ${Math.floor((stats.uptime % 3600) / 60)}m`)}</span>
        )}
      </div>
    </div>
  );
}
