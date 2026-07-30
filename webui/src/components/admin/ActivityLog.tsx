import { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import { Clock } from 'lucide-react';
import { useAuth } from '../../hooks/useAuth';
import { createUsersApi } from '../../api/users';
import type { ActivityLog } from '../../types/api';
import { useI18n } from '../../hooks/useI18n';
import { useInvalidation } from '../../hooks/useInvalidation';

export function ActivityLogView() {
  const { api } = useAuth();
  const usersApi = useMemo(() => createUsersApi(api), [api]);
  const { t } = useI18n();
  const [activities, setActivities] = useState<ActivityLog[]>([]);
  const requestGeneration = useRef(0);
  const mounted = useRef(true);

  const refreshActivity = useCallback(() => {
    const generation = ++requestGeneration.current;
    usersApi.getActivity().then(res => {
      if (mounted.current && generation === requestGeneration.current) setActivities(res.activities);
    }).catch(() => {});
  }, [usersApi]);
  useEffect(() => {
    mounted.current = true;
    refreshActivity();
    return () => { mounted.current = false; requestGeneration.current += 1; };
  }, [refreshActivity]);
  useInvalidation(['users', 'shares', 'stats'], refreshActivity);

  return (
    <div>
      <h3 className="text-lg font-semibold text-white mb-4">{t('admin.activity')}</h3>
      {activities.length === 0 ? (
        <p className="text-sm text-slate-500">{t('admin.no_activity')}</p>
      ) : (
        <div className="space-y-2">
          {activities.map(activity => (
            <div key={activity.id} className="flex items-start gap-3 px-4 py-2.5 rounded-lg bg-slate-800/30 border border-slate-700/50">
              <Clock size={14} className="text-slate-500 mt-1" />
              <div className="flex-1 min-w-0">
                <p className="text-sm text-slate-200">
                  <span className="text-brand-400">{activity.username}</span>
                  {' '}{activity.action}
                </p>
                <p className="text-xs text-slate-500">{activity.details}</p>
              </div>
              <span className="text-xs text-slate-600 whitespace-nowrap">
                {new Date(activity.timestamp).toLocaleString()}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
