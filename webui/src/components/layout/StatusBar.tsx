import { useState, useEffect } from 'react';
import { useAuth } from '../../hooks/useAuth';
import { createSystemApi } from '../../api/system';
import { useWebSocket } from '../../hooks/useWebSocket';
import type { StatsResponse } from '../../types/api';

interface StatusBarProps {
  sidebarOpen: boolean;
  infoOpen: boolean;
}

export function StatusBar(_props: StatusBarProps) {
  const { api, token } = useAuth();
  const systemApi = createSystemApi(api);
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [wsStatus] = useState<'connecting' | 'connected' | 'disconnected'>('disconnected');

  useWebSocket({
    getToken: () => token,
    onEvent: () => {},
    enabled: true,
  });

  useEffect(() => {
    const load = () => {
      systemApi.getStats().then(setStats).catch(() => {});
    };
    load();
    const timer = setInterval(load, 10000);
    return () => clearInterval(timer);
  }, [systemApi]);

  return (
    <div className="h-7 flex items-center text-[10px] text-slate-500 px-3 border-t border-slate-700/50 bg-slate-900/80 flex-shrink-0">
      <div className="flex items-center gap-3 flex-1 min-w-0">
        {stats && (
          <>
            <span>{stats.connections} connections</span>
            <span>·</span>
            <span>{stats.requests} requests</span>
            <span>·</span>
            <span>{stats.bytes_transferred_fmt}</span>
          </>
        )}
      </div>
      <div className="flex items-center gap-3">
        <span className="flex items-center gap-1">
          <span className={`w-1.5 h-1.5 rounded-full ${wsStatus === 'connected' ? 'bg-green-500' : wsStatus === 'connecting' ? 'bg-yellow-500' : 'bg-slate-600'}`} />
          {wsStatus === 'connected' ? 'Live' : wsStatus === 'connecting' ? 'Connecting...' : 'Offline'}
        </span>
        {stats && stats.uptime > 0 && (
          <span>Uptime: {Math.floor(stats.uptime / 3600)}h {Math.floor((stats.uptime % 3600) / 60)}m</span>
        )}
      </div>
    </div>
  );
}